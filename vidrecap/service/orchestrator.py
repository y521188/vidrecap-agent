"""主调度器：并行派发分片、进度回调、80% 增量摘要、最终语义融合。

本层只负责执行：参数从数据层的 PipelineConfig 来，分片窗口从规划层来，
压缩也交给规划层决策 + 本层递归。这里没有任何"策略数字"。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from vidrecap.data.api import PartialSummary, PipelineConfig, RecapResult, RecapStats, Shard
from vidrecap.external.api import LLMClient, MediaSource
from vidrecap.service.compressor import compress
from vidrecap.service.sharder import shard

ProgressCallback = Callable[[int, int], None]


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
    ) -> None:
        self.llm = llm
        self.config = config or PipelineConfig()
        self.on_progress = on_progress

    async def run(self, source: MediaSource) -> RecapResult:
        cfg = self.config
        shards = shard(source, cfg.shard_seconds, cfg.overlap_seconds)
        total = len(shards)
        semaphore = asyncio.Semaphore(cfg.max_concurrency)
        results: dict[int, PartialSummary] = {}
        state = {"done": 0, "incremental_task": None}
        incremental_target = max(1, round(total * cfg.incremental_at))
        chars_in = sum(len(s.text) for s in shards)

        async def summarize_one(s: Shard) -> PartialSummary:
            async with semaphore:
                started = time.perf_counter()
                summary = await self.llm.summarize(
                    s.text, instruction="概括该视频片段的场景、人物与事件"
                )
                partial = PartialSummary(
                    shard_index=s.index,
                    summary=summary,
                    elapsed_sec=time.perf_counter() - started,
                )
            results[s.index] = partial
            state["done"] += 1
            if self.on_progress:
                self.on_progress(state["done"], total)
            # 进度达标时异步先产出一版增量局部摘要，不等剩余分片
            if state["done"] == incremental_target and state["incremental_task"] is None:
                state["incremental_task"] = asyncio.create_task(
                    self._merge(list(results.values()))
                )
            return partial

        partials = await asyncio.gather(*(summarize_one(s) for s in shards))
        recap, rounds = await self._merge(partials)
        incremental_recap = None
        if state["incremental_task"] is not None:
            incremental_recap, _ = await state["incremental_task"]

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
) -> RecapResult:
    """任务级入口：命令行、将来的服务化封装、测试都从这里发起任务。

    三条入口走同一个门，行为才不会各走各的。
    """
    return await Orchestrator(llm, config=config, on_progress=on_progress).run(source)
