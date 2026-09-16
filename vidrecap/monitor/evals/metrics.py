"""指标计算：纯函数，输入用例与打分结果，输出比例数字。

不用任何第三方数值库——数据量小，手写反而更透明、更好核对。

**判"过/不过"用的是规则层的达标判定**（阈值 + 单项一票否决），
不是简单地看总分过没过线：线上修正闸门用的就是这套判定，
考卷必须量同一个东西，否则会出现"考卷说好、线上说坏"的分裂。
"""

from __future__ import annotations

from vidrecap.data.api import QualityConfig, SentenceScore
from vidrecap.monitor.evals.schemas import (
    CorrectionOutcome,
    CorrectorMetrics,
    ScorerCase,
    ScorerMetrics,
)
from vidrecap.rules.api import is_acceptable

# 同分时的计分：不打不罚，算半分（与常用的排序指标口径一致）
_TIE_CREDIT = 0.5


def _paired(
    cases: list[ScorerCase], scores: list[SentenceScore]
) -> list[tuple[ScorerCase, SentenceScore]]:
    if len(cases) != len(scores):
        raise ValueError(f"用例数与打分结果数不一致：{len(cases)} vs {len(scores)}")
    if not cases:
        raise ValueError("考卷为空，无法计算指标")
    return list(zip(cases, scores, strict=True))


def threshold_accuracy(
    cases: list[ScorerCase],
    scores: list[SentenceScore],
    config: QualityConfig | None = None,
) -> float:
    """判"过/不过"与标准答案一致的比例。"""
    paired = _paired(cases, scores)
    correct = sum(
        1 for case, score in paired if is_acceptable(score, config) == case.gold.passed
    )
    return correct / len(paired)


def pairwise_ranking_accuracy(
    cases: list[ScorerCase], scores: list[SentenceScore]
) -> float:
    """所有（好句, 坏句）配对中，好句分数更高的比例。

    比阈值准确率更细：即便过/不过都判对了，好句也该明显高于坏句。
    同分算半分。
    """
    paired = _paired(cases, scores)
    good = [score.total for case, score in paired if case.gold.passed]
    bad = [score.total for case, score in paired if not case.gold.passed]
    if not good or not bad:
        raise ValueError("考卷里必须同时有好句与坏句，否则排序正确率没有意义")

    credit = 0.0
    for good_score in good:
        for bad_score in bad:
            if good_score > bad_score:
                credit += 1.0
            elif good_score == bad_score:
                credit += _TIE_CREDIT
    return credit / (len(good) * len(bad))


def per_category_accuracy(
    cases: list[ScorerCase],
    scores: list[SentenceScore],
    config: QualityConfig | None = None,
) -> dict[str, float]:
    """按类别拆开的阈值准确率，用来看打分器在哪类病句上翻车。"""
    buckets: dict[str, list[tuple[ScorerCase, SentenceScore]]] = {}
    for case, score in _paired(cases, scores):
        buckets.setdefault(case.category, []).append((case, score))

    return {
        category: sum(
            1 for case, score in items if is_acceptable(score, config) == case.gold.passed
        )
        / len(items)
        for category, items in sorted(buckets.items())
    }


def scorer_misses(
    cases: list[ScorerCase],
    scores: list[SentenceScore],
    config: QualityConfig | None = None,
) -> list[str]:
    """判错的用例 id 列表。"""
    return [
        case.id
        for case, score in _paired(cases, scores)
        if is_acceptable(score, config) != case.gold.passed
    ]


def scorer_metrics(
    cases: list[ScorerCase],
    scores: list[SentenceScore],
    config: QualityConfig | None = None,
) -> ScorerMetrics:
    """把上面几个指标打包成一份打分器成绩单。"""
    return ScorerMetrics(
        case_count=len(cases),
        threshold_accuracy=threshold_accuracy(cases, scores, config),
        pairwise_ranking_accuracy=pairwise_ranking_accuracy(cases, scores),
        per_category_accuracy=per_category_accuracy(cases, scores, config),
        misses=scorer_misses(cases, scores, config),
    )


def corrector_metrics(outcomes: list[CorrectionOutcome]) -> CorrectorMetrics:
    """把逐条修正结果打包成修正器成绩单。

    四条指标的口径：

    - **修正成功率**：只统计"本来不达标"的句子，看修完有多少达标；
    - **无幻觉率**：结果里没有原文外实体的比例（护栏回退机制保证满分）；
    - **不倒退率**：修正后分数不低于修正前的比例（同上）；
    - **好句不动率**：本来达标的句子里，没有被改动的比例。

    某个口径下没有对应用例时按满分处理——没有可犯的错，就不该扣分。
    """
    if not outcomes:
        raise ValueError("没有修正结果，无法计算指标")

    needed = [outcome for outcome in outcomes if outcome.needed_fix]
    already_fine = [outcome for outcome in outcomes if not outcome.needed_fix]

    fix_rate = (
        sum(1 for outcome in needed if outcome.passed_after) / len(needed)
        if needed
        else 1.0
    )
    noop_safety_rate = (
        sum(1 for outcome in already_fine if not outcome.changed) / len(already_fine)
        if already_fine
        else 1.0
    )
    no_hallucination_rate = sum(1 for o in outcomes if not o.hallucinated) / len(outcomes)
    no_regression_rate = sum(1 for o in outcomes if o.score_after >= o.score_before) / len(
        outcomes
    )

    misses = [
        outcome.case_id
        for outcome in outcomes
        if outcome.hallucinated
        or outcome.missing_entities
        or (outcome.needed_fix and not outcome.passed_after)
        or (not outcome.needed_fix and outcome.changed)
    ]

    return CorrectorMetrics(
        case_count=len(outcomes),
        fix_rate=fix_rate,
        no_hallucination_rate=no_hallucination_rate,
        no_regression_rate=no_regression_rate,
        noop_safety_rate=noop_safety_rate,
        misses=misses,
    )
