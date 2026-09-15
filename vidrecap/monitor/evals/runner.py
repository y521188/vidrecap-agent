"""跑分器：把考卷喂给被测对象，算出成绩单。

对同一套考卷，换不同的被测对象就能横向对比（启发式 vs 真实大模型）。
逐条打分是顺序进行的——启发式实现是纯计算，等待成本可以忽略；
将来接模型档打分器时，慢的是模型本身，这里也不必改成并发去压上游。
"""

from __future__ import annotations

from vidrecap.data.api import QualityConfig
from vidrecap.external.api import QualityScorer, SentenceCorrector
from vidrecap.monitor.evals.loader import load_scorer_cases
from vidrecap.monitor.evals.metrics import scorer_metrics
from vidrecap.monitor.evals.schemas import (
    BaselineCheck,
    CorrectorCase,
    CorrectorMetrics,
    EvalReport,
    ScorerCase,
    ScorerMetrics,
)
from vidrecap.rules.api import (
    SCORER_MIN_PAIRWISE_RANKING_ACCURACY,
    SCORER_MIN_THRESHOLD_ACCURACY,
    HeuristicScorer,
)

AVAILABLE_SUITES = ("scorer", "corrector", "all")


async def run_scorer_eval(
    scorer: QualityScorer,
    cases: list[ScorerCase] | None = None,
    config: QualityConfig | None = None,
) -> ScorerMetrics:
    """跑 A 层考卷，产出打分器成绩单（不传考卷时用内置的 scorer_v1）。"""
    cfg = config or QualityConfig()
    loaded = cases if cases is not None else load_scorer_cases()
    scores = [await scorer.score(case.sentence, case.context) for case in loaded]
    return scorer_metrics(loaded, scores, cfg)


async def run_corrector_eval(
    corrector: SentenceCorrector,
    scorer: QualityScorer,
    cases: list[CorrectorCase] | None = None,
    config: QualityConfig | None = None,
) -> CorrectorMetrics:
    """跑 B 层考卷：先用打分器取修正前分数，修正后重打分并过护栏。"""
    raise NotImplementedError("待第 3 次提交实现：修正器跑分器")


async def run_eval(suite: str = "scorer", config: QualityConfig | None = None) -> EvalReport:
    """命令行入口用的总跑分：默认用规则层的启发式打分器与内置考卷。"""
    if suite not in AVAILABLE_SUITES:
        raise ValueError(f"未知的考卷：{suite}（可选 {', '.join(AVAILABLE_SUITES)}）")

    cfg = config or QualityConfig()
    if suite in {"corrector", "all"}:
        raise NotImplementedError("待第 3 次提交实现：修正器跑分器")

    return EvalReport(
        suite=suite,
        threshold=cfg.threshold,
        scorer=await run_scorer_eval(HeuristicScorer(cfg), None, cfg),
    )


def baseline_checks(report: EvalReport) -> list[BaselineCheck]:
    """把成绩单与规则层定义的基线逐条对照。

    基线数值归规则层（标准只写一处），"谁不达标"这个判断归本层；
    用户层只是把结果打印出来，不自己碰标准。
    """
    checks: list[BaselineCheck] = []

    if report.scorer is not None:
        checks.append(
            BaselineCheck(
                name="阈值准确率",
                measured=report.scorer.threshold_accuracy,
                required=SCORER_MIN_THRESHOLD_ACCURACY,
            )
        )
        checks.append(
            BaselineCheck(
                name="排序正确率",
                measured=report.scorer.pairwise_ranking_accuracy,
                required=SCORER_MIN_PAIRWISE_RANKING_ACCURACY,
            )
        )

    return checks
