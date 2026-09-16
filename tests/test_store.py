"""断点续跑测试：内容寻址缓存、中断重跑省钱、结果与一次跑完一致、指纹作废。"""

from vidrecap.data.api import PipelineConfig, TaskStore
from vidrecap.external.api import DemoCorrector, DemoSource
from vidrecap.rules.api import HeuristicScorer
from vidrecap.service.api import run_recap


class ContentLLM:
    """摘要只取决于输入文本；dies_after 次之后一直失败，模拟中途挂掉。"""

    def __init__(self, dies_after: int | None = None) -> None:
        self.dies_after = dies_after
        self.calls = 0

    async def summarize(self, text: str, instruction: str = "") -> str:
        self.calls += 1
        if self.dies_after is not None and self.calls > self.dies_after:
            raise RuntimeError("模型挂了")
        return f"摘要[{len(text)}]。"


def _config(**overrides) -> PipelineConfig:
    return PipelineConfig(
        shard_seconds=600,
        overlap_seconds=30,
        max_concurrency=1,
        max_retries=0,
        **overrides,
    )


async def test_interrupted_run_resumes_without_recalling_finished_shards(tmp_path):
    store_path = tmp_path / "cache.db"
    first = ContentLLM(dies_after=2)
    with TaskStore(store_path) as store:
        # 默认 skip 策略：跑到一半模型挂了，挂掉的片记账跳过，成功的片已入库
        interrupted = await run_recap(DemoSource(hours=1.0), first, _config(), store=store)
    assert first.calls == 6  # 每片恰好调一次（重试为 0），后 4 片全部失败
    assert interrupted.stats.failed_shards == 4

    resume_llm = ContentLLM()
    with TaskStore(store_path) as store:
        resumed = await run_recap(DemoSource(hours=1.0), resume_llm, _config(), store=store)
    assert resume_llm.calls == 4  # 只重算失败过的 4 片
    assert resumed.stats.failed_shards == 0

    reference_llm = ContentLLM()
    reference = await run_recap(DemoSource(hours=1.0), reference_llm, _config())
    assert resumed.recap == reference.recap  # 断点续跑 == 一次跑完
    assert [p.summary for p in resumed.partials] == [p.summary for p in reference.partials]
    assert reference_llm.calls == 6


async def test_store_reuses_identical_shards_only(tmp_path):
    llm = ContentLLM()
    with TaskStore(tmp_path / "cache.db") as store:
        first = await run_recap(DemoSource(hours=1.0), llm, _config(), store=store)
        rerun = await run_recap(DemoSource(hours=1.0), llm, _config(), store=store)
        longer = await run_recap(DemoSource(hours=1.5), llm, _config(), store=store)
    assert llm.calls == 6 + 0 + 4  # 重算的 4 片 = 末片（时长截断让文本变了）+ 3 片全新；前 5 片逐字相同直接命中
    assert rerun.recap == first.recap
    assert len(longer.partials) == 9


async def test_namespace_switch_invalidates_cache(tmp_path):
    a, b = ContentLLM(), ContentLLM()
    with TaskStore(tmp_path / "cache.db", namespace="model-a") as store:
        await run_recap(DemoSource(hours=1.0), a, _config(), store=store)
    with TaskStore(tmp_path / "cache.db", namespace="model-b") as store:
        await run_recap(DemoSource(hours=1.0), b, _config(), store=store)
    assert a.calls == 6 and b.calls == 6  # 换了模型（命名空间）一律重算


async def test_quality_fields_survive_the_cache_roundtrip(tmp_path):
    llm = ContentLLM()
    kwargs = dict(scorer=HeuristicScorer(), corrector=DemoCorrector())
    with TaskStore(tmp_path / "cache.db") as store:
        first = await run_recap(
            DemoSource(hours=1.0), llm, _config(), store=store, **kwargs
        )
        rerun = await run_recap(
            DemoSource(hours=1.0), llm, _config(), store=store, **kwargs
        )
    assert llm.calls == 6  # 第二次全程走缓存
    assert first.partials[0].avg_quality is not None
    assert [p.avg_quality for p in rerun.partials] == [p.avg_quality for p in first.partials]
    assert [p.corrected_count for p in rerun.partials] == [p.corrected_count for p in first.partials]
