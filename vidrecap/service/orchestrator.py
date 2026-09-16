"""主调度器：并行派发分片、进度回调、80% 增量摘要、最终语义融合。

本层只负责执行：参数从数据层的 PipelineConfig 来，分片窗口从规划层来，
压缩也交给规划层决策 + 本层递归。这里没有任何"策略数字"。

质检回路（可选）：传入 scorer 与 corrector 后，每个分片的局部摘要产出后
立刻过一遍"按句打分 → 低分修正 → 重打分 → 护栏"，不过关的句子回退原样。
不传这两个参数时行为与从前完全一致——质检是加法，不是改动。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from vidrecap.data.api import (
    PartialSummary,
    PipelineConfig,
    QualityConfig,
    RecapResult,
    RecapStats,
    Shard,
    SpeakerPlan,
    SpeakerPolicyConfig,
    TaskStore,
)
from vidrecap.external.api import (
    ContentCatalog,
    LLMClient,
    MediaSource,
    QualityScorer,
    SentenceCorrector,
)
from vidrecap.planning.api import plan_speaker_policy
from vidrecap.service.compressor import compress
from vidrecap.service.corrector import apply_corrections
from vidrecap.service.sharder import shard

ProgressCallback = Callable[[int, int], None]


async def _retry(call: Callable[[], Awaitable[str]], config: PipelineConfig) -> str:
    """指数退避重试：LLM 的超时与限流大多是暂时的，值得再敲几次门。"""
    delay = config.retry_initial_delay
    attempt = 0
    while True:
        try:
            return await call()
        except Exception:
            if attempt >= config.max_retries:
                raise
            attempt += 1
            await asyncio.sleep(delay)
            delay *= config.retry_backoff


class Orchestrator:
    """驱动一次"长视频 -> 分片并行摘要 -> 全局概括"的完整流程。

    on_progress(done, total) 在每个分片完成时被调用，可用来画进度条。
    回调类型 ProgressCallback 是本层对外承诺的一部分，由调用方（监控层、
    用户层）实现并注入——服务层不反向依赖它们。
    """

    def __init__(
        self,
        llm: LLMClient,
        config: PipelineConfig | None = None,
        on_progress: ProgressCallback | None = None,
        scorer: QualityScorer | None = None,
        corrector: SentenceCorrector | None = None,
        quality_config: QualityConfig | None = None,
        store: TaskStore | None = None,
        catalog: ContentCatalog | None = None,
        speaker_config: SpeakerPolicyConfig | None = None,
    ) -> None:
        self.llm = llm
        self.config = config or PipelineConfig()
        self.on_progress = on_progress
        self.scorer = scorer
        self.corrector = corrector
        self.quality_config = quality_config
        self.store = store
        self.catalog = catalog
        self.speaker_config = speaker_config

    async def run(self, source: MediaSource) -> RecapResult:
        cfg = self.config
        store = self.store
        # 人物策略：计划由规划层出（大咖保留、配角过滤），本层照计划取材
        plan: SpeakerPlan | None = None
        if self.catalog is not None:
            all_lines = await self.catalog.lines(0, source.duration())
            profiles = await self.catalog.speaker_profiles()
            plan = plan_speaker_policy(all_lines, profiles, self.speaker_config)
        shards = shard(
            source,
            cfg.shard_seconds,
            cfg.overlap_seconds,
            lines=plan.keep if plan else None,
        )
        total = len(shards)
        semaphore = asyncio.Semaphore(cfg.max_concurrency)
        results: dict[int, PartialSummary] = {}
        state = {"done": 0, "incremental_task": None}
        incremental_target = max(1, round(total * cfg.incremental_at))
        chars_in = sum(len(s.text) for s in shards)

        def _finish(partial: PartialSummary) -> PartialSummary:
            """记下成果、报进度；进度达标时异步先产出一版增量局部摘要。"""
            results[partial.shard_index] = partial
            state["done"] += 1
            if self.on_progress:
                self.on_progress(state["done"], total)
            if state["done"] == incremental_target and state["incremental_task"] is None:
                state["incremental_task"] = asyncio.create_task(
                    self._merge(list(results.values()))
                )
            return partial

        async def summarize_one(s: Shard) -> PartialSummary | None:
            key = store.key(s.text) if store is not None else None
            if key is not None:
                cached = store.load(key, s.index)
                if cached is not None:
                    # 缓存命中不占并发名额：没有模型调用，不值得排队
                    return _finish(cached)
            async with semaphore:
                started = time.perf_counter()
                try:
                    summary = await _retry(
                        lambda: self.llm.summarize(
                            s.text, instruction=cfg.summarize_instruction
                        ),
                        cfg,
                    )
                except Exception:
                    if cfg.on_shard_failure == "raise":
                        raise
                    # 降级：放弃这片，但记账、报进度，绝不静默
                    state["done"] += 1
                    if self.on_progress:
                        self.on_progress(state["done"], total)
                    return None
                partial = PartialSummary(shard_index=s.index, summary=summary)
                if self.scorer is not None and self.corrector is not None:
                    # 质检也占一个并发名额：修正本身可能又是一次模型调用
                    partial = (
                        await apply_corrections(
                            [partial],
                            {s.index: s.text},
                            self.scorer,
                            self.corrector,
                            self.quality_config,
                        )
                    )[0]
                partial = partial.model_copy(
                    update={"elapsed_sec": time.perf_counter() - started}
                )
                if key is not None:
                    store.save(key, partial)  # 质检之后的最终结果才进缓存
            return _finish(partial)

        gathered = await asyncio.gather(*(summarize_one(s) for s in shards))
        partials = [p for p in gathered if p is not None]
        recap, rounds = await self._merge(partials)
        incremental_recap = None
        if state["incremental_task"] is not None:
            incremental_recap, _ = await state["incremental_task"]

        quality_values = [p.avg_quality for p in partials if p.avg_quality is not None]
        stats = RecapStats(
            duration_sec=source.duration(),
            shard_count=total,
            shard_seconds=cfg.shard_seconds,
            overlap_seconds=cfg.overlap_seconds,
            partial_count=len(partials),
            compression_rounds=rounds,
            incremental_at=cfg.incremental_at,
            chars_in=chars_in,
            chars_out=len(recap),
            corrected_count=sum(p.corrected_count for p in partials),
            failed_shards=total - len(partials),
            dropped_lines=len(plan.drop) if plan else 0,
            dropped_speakers=plan.dropped_speakers if plan else [],
            avg_quality=(sum(quality_values) / len(quality_values)) if quality_values else None,
        )
        return RecapResult(
            recap=recap, partials=partials, incremental_recap=incremental_recap, stats=stats
        )

    async def _merge(self, partials: list[PartialSummary]) -> tuple[str, int]:
        """按时序拼接局部摘要；超限则交给二分递归压缩收敛。"""
        ordered = sorted(partials, key=lambda p: p.shard_index)
        body = "\n\n".join(
            f"[片段{i + 1}] {p.summary}" for i, p in enumerate(ordered)
        )
        return await compress(body, self.config.context_limit, self.llm)


async def run_recap(
    source: MediaSource,
    llm: LLMClient,
    config: PipelineConfig | None = None,
    on_progress: ProgressCallback | None = None,
    scorer: QualityScorer | None = None,
    corrector: SentenceCorrector | None = None,
    quality_config: QualityConfig | None = None,
    store: TaskStore | None = None,
    catalog: ContentCatalog | None = None,
    speaker_config: SpeakerPolicyConfig | None = None,
) -> RecapResult:
    """任务级入口：命令行、将来的服务化封装、测试都从这里发起任务。

    三条入口走同一个门，行为才不会各走各的。
    """
    return await Orchestrator(
        llm,
        config=config,
        on_progress=on_progress,
        scorer=scorer,
        corrector=corrector,
        quality_config=quality_config,
        store=store,
        catalog=catalog,
        speaker_config=speaker_config,
    ).run(source)
