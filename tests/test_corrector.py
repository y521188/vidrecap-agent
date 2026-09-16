"""修正流程测试：断句一致性、修正计划、忠实性护栏、回退与降级、流水线接入。"""

from vidrecap.data.api import PartialSummary, PipelineConfig
from vidrecap.external.api import DemoCorrector, DemoLLM, DemoSource
from vidrecap.planning.api import plan_corrections, split_sentences
from vidrecap.rules.api import HeuristicScorer, check_faithfulness, extract_entities
from vidrecap.service.api import apply_corrections, run_recap

GOOD = "主持人介绍了节目制作流程，并说明了审核标准。"
BAD_NO_SUBJECT = "介绍了节目制作流程，并说明了审核标准。"
CONTEXT = "主持人介绍了节目制作流程，并说明了审核标准。现场观众反响热烈。"


class FakeCorrector:
    """按脚本返回修正结果的假修正器。"""

    def __init__(self, replacement: str) -> None:
        self.replacement = replacement
        self.calls = 0

    async def correct(self, sentence: str, context: str) -> str:
        self.calls += 1
        return self.replacement


class ExplodingCorrector:
    async def correct(self, sentence: str, context: str) -> str:
        raise RuntimeError("修正器挂了")


async def _run(partials, corrector, scorer=None, config=None):
    return await apply_corrections(
        partials,
        {p.shard_index: CONTEXT for p in partials},
        scorer or HeuristicScorer(),
        corrector,
        config,
    )


# --- 断句：两份实现必须一致 ---


def test_demo_splitter_agrees_with_planning_splitter():
    """外部层与规划层各有一份断句实现（依赖规矩不允许共用），必须保持一致。"""
    from vidrecap.external.adapters.demo.text import split_sentences as demo_split

    samples = [
        "第一句。第二句！第三句？",
        "没有标点的残句",
        "混合内容。带英文的 sentence。最后一句",
        "",
        "只有标点。，！？",
    ]
    for text in samples:
        assert demo_split(text) == split_sentences(text), text


def test_splitter_keeps_truncated_tail():
    assert split_sentences("完整句。没说完的半句") == ["完整句。", "没说完的半句"]


# --- 修正计划 ---


async def test_plan_picks_only_sentences_below_the_bar():
    scorer = HeuristicScorer()
    sentences = [GOOD, BAD_NO_SUBJECT]
    scores = [await scorer.score(text, CONTEXT) for text in sentences]

    plan = plan_corrections(sentences, scores)
    assert [target.index for target in plan.targets] == [1]
    assert plan.targets[0].sentence == BAD_NO_SUBJECT
    assert plan.targets[0].reason


async def test_plan_is_empty_when_everything_passes():
    scorer = HeuristicScorer()
    scores = [await scorer.score(GOOD, CONTEXT)]
    assert plan_corrections([GOOD], scores).targets == []


def test_plan_rejects_mismatched_lengths():
    import pytest

    with pytest.raises(ValueError, match="不一致"):
        plan_corrections([GOOD], [])


# --- 忠实性护栏 ---


def test_guardrail_passes_a_faithful_sentence():
    assert check_faithfulness(GOOD, CONTEXT) == []


def test_guardrail_catches_a_fabricated_entity():
    fabricated = "主持人介绍了节目制作流程，并公布了明年的档期安排。"
    violations = check_faithfulness(fabricated, CONTEXT)
    assert "公布了明年的档期安排" in violations


def test_guardrail_allows_rewording_that_reuses_source_fragments():
    """换断句、换语序的合法改写不该被判成幻觉。"""
    reworded = "节目制作流程与审核标准，主持人介绍了。"
    assert check_faithfulness(reworded, CONTEXT) == []


def test_guardrail_ignores_connectives_not_in_the_source():
    assert check_faithfulness("此外，主持人介绍了节目制作流程。", CONTEXT) == []


def test_guardrail_rejects_everything_when_there_is_no_context():
    assert check_faithfulness(GOOD, "") != []


def test_extract_entities_drops_function_words_and_single_chars():
    assert extract_entities("并且，他。主持人") == ["主持人"]


# --- 修正执行 ---


async def test_bad_sentence_gets_fixed_by_the_demo_corrector():
    partials = [PartialSummary(shard_index=0, summary=BAD_NO_SUBJECT)]
    [fixed] = await _run(partials, DemoCorrector())

    assert fixed.summary == GOOD
    assert fixed.corrected_count == 1
    assert fixed.avg_quality is not None and fixed.avg_quality >= 0.9


async def test_good_sentence_is_left_untouched():
    partials = [PartialSummary(shard_index=0, summary=GOOD)]
    [untouched] = await _run(partials, DemoCorrector())

    assert untouched.summary == GOOD
    assert untouched.corrected_count == 0


async def test_hallucinated_correction_is_reverted():
    """修正结果里冒出原文没有的实体时，宁可保留原句。"""
    fabricated = "主持人宣布明年的档期已经排满。"
    partials = [PartialSummary(shard_index=0, summary=BAD_NO_SUBJECT)]
    [reverted] = await _run(partials, FakeCorrector(fabricated))

    assert reverted.summary == BAD_NO_SUBJECT
    assert reverted.corrected_count == 0


async def test_worse_correction_is_reverted():
    truncated = "介绍了节目制作流程"  # 比原句更差：丢了主语还缺结尾标点
    partials = [PartialSummary(shard_index=0, summary=BAD_NO_SUBJECT)]
    [reverted] = await _run(partials, FakeCorrector(truncated))

    assert reverted.summary == BAD_NO_SUBJECT
    assert reverted.corrected_count == 0


async def test_a_failing_corrector_does_not_break_the_pipeline():
    partials = [PartialSummary(shard_index=0, summary=BAD_NO_SUBJECT)]
    [kept] = await _run(partials, ExplodingCorrector())

    assert kept.summary == BAD_NO_SUBJECT
    assert kept.corrected_count == 0


async def test_quality_is_recorded_even_without_any_correction():
    partials = [PartialSummary(shard_index=0, summary=GOOD)]
    [scored] = await _run(partials, DemoCorrector())

    assert scored.avg_quality is not None


# --- 接入流水线 ---


async def test_pipeline_without_scorer_keeps_the_old_behaviour():
    result = await run_recap(DemoSource(hours=0.5), DemoLLM(), PipelineConfig())
    assert result.stats.corrected_count == 0
    assert result.stats.avg_quality is None
    assert all(p.avg_quality is None for p in result.partials)


async def test_pipeline_with_quality_loop_reports_corrections():
    scorer = HeuristicScorer()
    result = await run_recap(
        DemoSource(hours=0.5),
        DemoLLM(),
        PipelineConfig(),
        scorer=scorer,
        corrector=DemoCorrector(),
    )
    assert result.stats.avg_quality is not None
    assert result.stats.corrected_count >= 1  # 假模型截断句子，必然有低分句
    assert all(p.avg_quality is not None for p in result.partials)


async def test_pipeline_quality_loop_is_deterministic():
    async def run_once():
        return await run_recap(
            DemoSource(hours=0.5),
            DemoLLM(),
            PipelineConfig(),
            scorer=HeuristicScorer(),
            corrector=DemoCorrector(),
        )

    first, second = await run_once(), await run_once()
    assert first.recap == second.recap
    assert first.stats == second.stats
