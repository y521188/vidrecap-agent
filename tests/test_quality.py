"""打分器测试：三指标各自的规则、加权公式、确定性、阈值闸门与插座形状。"""

import pytest

from vidrecap.data.api import QualityConfig, SentenceScore
from vidrecap.external.api import QualityScorer
from vidrecap.rules.api import (
    SEVERE_METRIC_FLOOR,
    HeuristicScorer,
    is_acceptable,
    unacceptable_reason,
)

# 好句对照：正常叙述、很短但完整、较长但清晰
GOOD_SENTENCES = [
    "主持人分析了媒体融合趋势，并结合案例给出了详细说明。",
    "主持人总结了节目流程。",
    "数据分析师回顾了平台推荐算法，并说明了内容审核标准的变化，同时提出了三条改进建议。",
]

# 缺主语：句首直接是谓语
MISSING_SUBJECT_SENTENCES = [
    "介绍了媒体融合趋势，并结合案例给出了详细说明。",
    "总结了节目制作流程。",
    "认为该方案可以推广。",
]

# 指代过密：指不明说的是谁、哪件事
VAGUE_PRONOUN_SENTENCES = [
    "他说了那个事情。",
    "他们讨论了这个，然后又说那个。",
]

# 不通顺：重复、连读、碎片
DISFLUENT_SENTENCES = [
    "栏目组介绍介绍了节目制作流程。",
    "栏目组介绍了节目制作流程并结合案例给出了详细说明还提出了改进建议",
    "了了。",
]

# 不完整：截断、半截话
INCOMPLETE_SENTENCES = [
    "栏目组介绍了节目制作流程",
    "栏目组介绍了节目制作流程，",
]


def _scorer(**config_kwargs) -> HeuristicScorer:
    return HeuristicScorer(QualityConfig(**config_kwargs))


async def _score(sentence: str, context: str = "", **config_kwargs) -> SentenceScore:
    return await _scorer(**config_kwargs).score(sentence, context)


# --- 插座形状与确定性 ---


def test_scorer_matches_the_socket_shape():
    assert isinstance(HeuristicScorer(), QualityScorer)


@pytest.mark.parametrize("sentence", GOOD_SENTENCES + MISSING_SUBJECT_SENTENCES)
async def test_scoring_is_deterministic(sentence: str):
    first = await _score(sentence)
    second = await _score(sentence)
    assert first == second


# --- 好句对照 ---


@pytest.mark.parametrize("sentence", GOOD_SENTENCES)
async def test_good_sentences_score_high_and_pass(sentence: str):
    score = await _score(sentence)
    assert score.clarity == 1.0
    assert score.fluency == 1.0
    assert score.completeness == 1.0
    assert score.total >= 0.9
    assert score.reasons == []
    assert is_acceptable(score)


async def test_context_does_not_affect_the_heuristic_score():
    """完整度刻意不查信息覆盖率，所以换原文不该改变分数。"""
    sentence = "主持人总结了节目流程。"
    short_context = await _score(sentence, context="主持人总结了节目流程。")
    long_context = await _score(sentence, context="详细内容。" * 200)
    assert short_context == long_context


# --- 清晰度 ---


@pytest.mark.parametrize("sentence", MISSING_SUBJECT_SENTENCES)
async def test_missing_subject_lowers_clarity_and_fails_gate(sentence: str):
    score = await _score(sentence)
    assert score.clarity < SEVERE_METRIC_FLOOR
    assert any("缺主语" in reason for reason in score.reasons)
    assert not is_acceptable(score)


@pytest.mark.parametrize("sentence", VAGUE_PRONOUN_SENTENCES)
async def test_vague_pronouns_lower_clarity_and_fail_gate(sentence: str):
    score = await _score(sentence)
    assert score.clarity < SEVERE_METRIC_FLOOR
    assert any("指代" in reason for reason in score.reasons)
    assert not is_acceptable(score)


async def test_pronoun_rule_does_not_flag_words_that_merely_contain_them():
    """「其他」里的「他」不是指代，不能算进去。"""
    score = await _score("其他嘉宾也发言了。")
    assert score.clarity == 1.0
    assert not any("指代" in reason for reason in score.reasons)


async def test_known_limitation_short_sentence_with_resolvable_pronoun_is_flagged():
    """已知局限：短句里出现一次指代就会被判低分，哪怕指代在上下文中其实很清楚。

    因为启发式打分器**看不见上下文**（这是刻意的：它必须确定性、零依赖、可离线复现），
    只能按指代词密度判断。"他们决定重拍开场。"这类句子会被误判。
    这个局限留着不修，是因为修它就得引入上下文理解——那属于模型档打分器的活，
    届时应在这套考卷的同一批题上做对比。此测试锁住现状，避免有人误以为它"已经能处理指代"。
    """
    score = await _score("他们决定重拍开场。", context="栏目组和嘉宾讨论后，他们决定重拍开场。")
    assert score.clarity < SEVERE_METRIC_FLOOR
    assert not is_acceptable(score)


# --- 通顺度 ---


@pytest.mark.parametrize("sentence", DISFLUENT_SENTENCES)
async def test_disfluent_sentences_lower_fluency(sentence: str):
    score = await _score(sentence)
    assert score.fluency < 0.8
    assert score.reasons


async def test_repeated_word_is_flagged_and_fails_gate():
    score = await _score("栏目组介绍介绍了节目制作流程。")
    assert score.fluency < SEVERE_METRIC_FLOOR
    assert any("重复" in reason for reason in score.reasons)
    assert not is_acceptable(score)


async def test_consecutive_punctuation_lowers_fluency():
    score = await _score("主持人总结了节目流程。。")
    assert score.fluency < 1.0
    assert any("标点" in reason for reason in score.reasons)


async def test_fragment_is_flagged():
    score = await _score("了了。")
    assert score.fluency < 1.0
    assert any("碎片" in reason for reason in score.reasons)


# --- 完整度 ---


@pytest.mark.parametrize("sentence", INCOMPLETE_SENTENCES)
async def test_incomplete_sentences_fail_gate(sentence: str):
    score = await _score(sentence)
    assert score.completeness < SEVERE_METRIC_FLOOR
    assert not is_acceptable(score)


async def test_truncated_sentence_is_flagged():
    score = await _score("栏目组介绍了节目制作流程")
    assert any("截断" in reason for reason in score.reasons)


async def test_half_stop_ending_is_flagged():
    score = await _score("栏目组介绍了节目制作流程，")
    assert any("一半" in reason for reason in score.reasons)


async def test_mixed_defects_collect_multiple_reasons():
    score = await _score("介绍介绍了那个。")
    assert len(score.reasons) >= 2
    assert not is_acceptable(score)


async def test_empty_sentence_is_rejected():
    score = await _score("")
    assert not is_acceptable(score)
    assert score.reasons


# --- 加权公式与配置 ---


async def test_total_follows_the_configured_weights():
    sentence = "介绍了媒体融合趋势。"
    clarity_only = await _score(sentence, clarity_weight=1.0, fluency_weight=0.0, completeness_weight=0.0)
    balanced = await _score(sentence)
    assert clarity_only.total == pytest.approx(clarity_only.clarity)
    assert balanced.total > clarity_only.total  # 通顺与完整两项仍在加分


async def test_threshold_is_configurable():
    # 用一句"略有瑕疵但能过默认阈值"的句子：默认配置放行，抬高峰值就拦下
    sentence = "其他嘉宾也发言了。"
    assert is_acceptable(await _score(sentence), QualityConfig())
    assert not is_acceptable(await _score(sentence), QualityConfig(threshold=0.99))


# --- 闸门：一票否决 ---


def test_gate_flunks_when_one_metric_is_severe_even_if_total_is_high():
    """加权平均会把明显缺陷抹平，所以单项严重不合格要一票否决。"""
    score = SentenceScore(
        sentence="栏目组介绍介绍了节目制作流程。",
        clarity=0.9,
        fluency=float(SEVERE_METRIC_FLOOR) - 0.1,
        completeness=0.9,
        total=0.85,
    )
    assert score.total >= QualityConfig().threshold
    assert not is_acceptable(score)
    assert "通顺度" in (unacceptable_reason(score) or "")


def test_gate_accepts_when_every_metric_is_above_the_floor():
    score = SentenceScore(
        sentence="主持人总结了节目流程。",
        clarity=1.0,
        fluency=float(SEVERE_METRIC_FLOOR),
        completeness=1.0,
        total=1.0,
    )
    assert is_acceptable(score)
    assert unacceptable_reason(score) is None


async def test_unacceptable_reason_reports_the_total_when_it_is_below_threshold():
    score = await _score("介绍介绍了那个。")  # 缺主语 + 重复 + 指代，总分被压到阈值以下
    assert score.total < QualityConfig().threshold
    reason = unacceptable_reason(score)
    assert reason is not None
    assert "总分" in reason
