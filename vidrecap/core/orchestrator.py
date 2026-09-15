"""主调度器：并行派发分片、进度回调、80% 增量摘要、最终语义融合。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from .compressor import compress
from .models import PartialSummary, RecapResult, RecapStats, Shard
from .protocols import LLMClient, MediaSource
from .sharder import shard

ProgressCallback = Callable[[int, int], None]


class Orchestrator:
    """驱动一次"长视频 -> 分片并行摘要 -> 全局概括"的完整流程。

    on_progress(done, total) 在每个分片完成时被调用，可用来画进度条。
    """

    def __init__(
        self,
        llm: LLMClient,
        shard_seconds: float = 600.0,
        overlap_seconds: float = 30.0,
        max_concurrency: int = 8,
        context_limit: int = 4000,
        incremental_at: float = 0.8,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        if not 0 < incremental_at <= 1.0:
            raise ValueError("incremental_at must be in (0, 1.0]")
        self.llm = llm
        self.shard_seconds = shard_seconds
        self.overlap_seconds = overlap_seconds
        self.max_concurrency = max_concurrency
        self.context_limit = context_limit
        self.incremental_at = incremental_at
        self.on_progress = on_progress

    async def run(self, source: MediaSource) -> RecapResult:
        shards = shard(source, self.shard_seconds, self.overlap_seconds)
        total = len(shards)
        semaphore = asyncio.Semaphore(self.max_concurrency)
        results: dict[int, PartialSummary] = {}
        state = {"done": 0, "incremental_task": None}
        incremental_target = max(1, round(total * self.incremental_at))
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
            shard_seconds=self.shard_seconds,
            overlap_seconds=self.overlap_seconds,
            partial_count=len(partials),
            compression_rounds=rounds,
            incremental_at=self.incremental_at,
            chars_in=chars_in,
            chars_out=len(recap),
        )
        return RecapResult(
            recap=recap, partials=partials, incremental_recap=incremental_recap, stats=stats
        )

    async def _merge(
        self, partials: list[PartialSummary]
    ) -> tuple[str, int]:
        """按时序拼接局部摘要；超限则交给二分递归压缩收敛。"""
        ordered = sorted(partials, key=lambda p: p.shard_index)
        body = "\n\n".join(
            f"[片段{i + 1}] {p.summary}" for i, p in enumerate(ordered)
        )
        return await compress(body, self.context_limit, self.llm)
