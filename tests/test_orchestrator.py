"""调度器集成测试：并行摘要、增量摘要触发、最终融合与统计、失败重试与降级。"""

import pytest

from vidrecap.data.api import PipelineConfig
from vidrecap.external.api import DemoLLM, DemoSource
from vidrecap.service.api import Orchestrator, run_recap


async def test_full_pipeline_produces_recap():
    llm = DemoLLM()
    config = PipelineConfig(
        shard_seconds=600, overlap_seconds=30, max_concurrency=4, context_limit=1200
    )
    result = await Orchestrator(llm, config=config).run(DemoSource(hours=1.0))

    assert result.stats.shard_count == 6
    assert len(result.partials) == 6
    assert [p.shard_index for p in result.partials] == list(range(6))
    assert result.recap
    assert llm.calls >= 6  # 每个分片至少一次摘要调用


async def test_task_level_entry_runs_same_pipeline():
    result = await run_recap(
        DemoSource(hours=1.0),
        DemoLLM(),
        PipelineConfig(shard_seconds=600, overlap_seconds=30, context_limit=1200),
    )
    assert result.stats.shard_count == 6
    assert result.recap


async def test_incremental_recap_triggered_at_progress_target():
    seen = []
    config = PipelineConfig(
        shard_seconds=600,
        overlap_seconds=30,
        context_limit=100000,  # 不触发压缩，隔离增量逻辑
        incremental_at=0.8,
    )
    orchestrator = Orchestrator(
        DemoLLM(),
        config=config,
        on_progress=lambda done, total: seen.append((done, total)),
    )
    result = await orchestrator.run(DemoSource(hours=1.0))

    assert result.incremental_recap is not None
    assert result.incremental_recap != result.recap
    assert seen == [(i, 6) for i in range(1, 7)]


async def test_config_values_flow_into_stats():
    config = PipelineConfig(shard_seconds=300, overlap_seconds=20)
    result = await Orchestrator(DemoLLM(), config=config).run(DemoSource(hours=0.5))
    assert result.stats.shard_count == 6
    assert result.stats.overlap_seconds == 20


async def test_stats_consistency():
    config = PipelineConfig(shard_seconds=600, overlap_seconds=30)
    result = await Orchestrator(DemoLLM(), config=config).run(DemoSource(hours=1.0))
    assert result.stats.chars_in > result.stats.chars_out > 0
    assert result.stats.duration_sec == 3600


# --- 失败重试与降级 ---


class FlakyLLM:
    """前 fail_times 次调用抛错，之后正常出摘要——用来验证重试。"""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def summarize(self, text: str, instruction: str = "") -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("模拟模型抽风")
        return f"摘要{self.calls}。"


def _retry_config(**overrides) -> PipelineConfig:
    return PipelineConfig(
        shard_seconds=600,
        overlap_seconds=30,
        context_limit=1200,
        retry_initial_delay=0.01,
        **overrides,
    )


async def test_transient_failure_is_retried_and_run_succeeds():
    llm = FlakyLLM(fail_times=1)
    result = await Orchestrator(llm, config=_retry_config()).run(DemoSource(hours=1.0))
    assert result.stats.failed_shards == 0
    assert len(result.partials) == 6
    assert llm.calls == 7  # 6 个分片 + 第 2 片撞上那 1 次失败后的重试


async def test_exhausted_retries_skip_shards_and_record_them():
    llm = FlakyLLM(fail_times=10**9)
    result = await Orchestrator(llm, config=_retry_config(max_retries=1)).run(
        DemoSource(hours=1.0)
    )
    assert result.stats.failed_shards == 6
    assert result.partials == []
    assert result.recap == ""
    assert llm.calls == 12  # 每片原始 1 次 + 重试 1 次，全部耗尽


async def test_raise_policy_fails_the_whole_task():
    llm = FlakyLLM(fail_times=10**9)
    with pytest.raises(RuntimeError, match="抽风"):
        await Orchestrator(
            llm, config=_retry_config(max_retries=1, on_shard_failure="raise")
        ).run(DemoSource(hours=1.0))


async def test_zero_retries_makes_exactly_one_call_per_shard():
    llm = FlakyLLM(fail_times=10**9)
    result = await Orchestrator(llm, config=_retry_config(max_retries=0)).run(
        DemoSource(hours=1.0)
    )
    assert llm.calls == 6
    assert result.stats.failed_shards == 6
