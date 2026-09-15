"""指标计算：纯函数，输入用例与打分结果，输出比例数字。

不用任何第三方数值库——数据量小，手写反而更透明、更好核对。
待第 2、3 次提交实现。
"""

from __future__ import annotations

from vidrecap.data.api import SentenceScore
from vidrecap.monitor.evals.schemas import (
    CorrectionOutcome,
    CorrectorMetrics,
    ScorerCase,
    ScorerMetrics,
)


def threshold_accuracy(
    cases: list[ScorerCase], scores: list[SentenceScore], threshold: float
) -> float:
    """判"过/不过"与标准答案一致的比例。"""
    raise NotImplementedError("待第 2 次提交实现：阈值准确率")


def pairwise_ranking_accuracy(
    cases: list[ScorerCase], scores: list[SentenceScore]
) -> float:
    """所有（好句, 坏句）配对中，好句分数更高的比例。

    比阈值准确率更细：即便都判对了过/不过，好句也该明显高于坏句。
    """
    raise NotImplementedError("待第 2 次提交实现：排序正确率")


def per_category_accuracy(
    cases: list[ScorerCase], scores: list[SentenceScore], threshold: float
) -> dict[str, float]:
    """按类别拆开的阈值准确率，用来看打分器在哪类病句上翻车。"""
    raise NotImplementedError("待第 2 次提交实现：分类别准确率")


def scorer_misses(
    cases: list[ScorerCase], scores: list[SentenceScore], threshold: float
) -> list[str]:
    """判错的用例 id 列表。"""
    raise NotImplementedError("待第 2 次提交实现：错题清单")


def scorer_metrics(
    cases: list[ScorerCase], scores: list[SentenceScore], threshold: float
) -> ScorerMetrics:
    """把上面几个指标打包成一份打分器成绩单。"""
    raise NotImplementedError("待第 2 次提交实现：打分器成绩单")


def corrector_metrics(outcomes: list[CorrectionOutcome]) -> CorrectorMetrics:
    """把逐条修正结果打包成修正器成绩单（成功率 / 无幻觉率 / 不倒退率）。"""
    raise NotImplementedError("待第 3 次提交实现：修正器成绩单")
