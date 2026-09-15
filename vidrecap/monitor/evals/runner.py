"""跑分器：把考卷喂给被测对象，算出成绩单。

对同一套考卷，换不同的被测对象就能横向对比（启发式 vs 真实大模型）。
待第 2、3 次提交实现。
"""

from __future__ import annotations

from vidrecap.data.api import QualityConfig
from vidrecap.external.api import QualityScorer, SentenceCorrector
from vidrecap.monitor.evals.schemas import (
    CorrectorCase,
    CorrectorMetrics,
    EvalReport,
    ScorerCase,
    ScorerMetrics,
)


async def run_scorer_eval(
    scorer: QualityScorer,
    cases: list[ScorerCase] | None = None,
    config: QualityConfig | None = None,
) -> ScorerMetrics:
    """跑 A 层考卷，产出打分器成绩单（不加载默认考卷时用内置的）。"""
    raise NotImplementedError("待第 2 次提交实现：打分器跑分器")


async def run_corrector_eval(
    corrector: SentenceCorrector,
    scorer: QualityScorer,
    cases: list[CorrectorCase] | None = None,
    config: QualityConfig | None = None,
) -> CorrectorMetrics:
    """跑 B 层考卷：先用打分器取修正前分数，修正后重打分并过护栏。"""
    raise NotImplementedError("待第 3 次提交实现：修正器跑分器")


async def run_eval(suite: str = "all", config: QualityConfig | None = None) -> EvalReport:
    """命令行入口用的总跑分：默认用规则层的启发式打分器与内置考卷。"""
    raise NotImplementedError("待第 2 次提交实现：总跑分入口")
