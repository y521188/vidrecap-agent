"""调度器集成测试：并行摘要、增量摘要触发、最终融合与统计。"""

from vidrecap.adapters.demo import DemoLLM, DemoSource
from vidrecap.core.orchestrator import Orchestrator


async def test_full_pipeline_produces_recap():
    llm = DemoLLM()
    orchestrator = Orchestrator(
        llm,
        shard_seconds=600,
        overlap_seconds=30,
        max_concurrency=4,
        context_limit=1200,
    )
    result = await orchestrator.run(DemoSource(hours=1.0))

    assert result.stats.shard_count == 6
    assert len(result.partials) == 6
    assert [p.shard_index for p in result.partials] == list(range(6))
    assert result.recap
    assert llm.calls >= 6  # 每个分片至少一次摘要调用


async def test_incremental_recap_triggered_at_progress_target():
    seen = []
    orchestrator = Orchestrator(
        DemoLLM(),
        shard_seconds=600,
        overlap_seconds=30,
        context_limit=100000,  # 不触发压缩，隔离增量逻辑
        incremental_at=0.8,
        on_progress=lambda done, total: seen.append((done, total)),
    )
    result = await orchestrator.run(DemoSource(hours=1.0))

    assert result.incremental_recap is not None
    assert result.incremental_recap != result.recap
    assert seen == [(i, 6) for i in range(1, 7)]


async def test_overlap_enabled_by_default_windows():
    orchestrator = Orchestrator(DemoLLM(), shard_seconds=300, overlap_seconds=20)
    result = await orchestrator.run(DemoSource(hours=0.5))
    assert result.stats.shard_count == 6
    assert result.stats.overlap_seconds == 20


async def test_stats_consistency():
    orchestrator = Orchestrator(DemoLLM(), shard_seconds=600, overlap_seconds=30)
    result = await orchestrator.run(DemoSource(hours=1.0))
    assert result.stats.chars_in > result.stats.chars_out > 0
    assert result.stats.duration_sec == 3600
