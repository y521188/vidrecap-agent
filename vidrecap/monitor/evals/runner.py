"""跑分器：把考卷喂给被测对象，算出成绩单。

对同一套考卷，换不同的被测对象就能横向对比（启发式 vs 真实大模型）。

修正器考卷**跑的是线上那套编排**（`service.apply_corrections`），不是另写一遍：
拆句、打分、挑句子、修正、重打分、过护栏、回退全部照旧。否则考卷量到的
只是"另写的评测版行为"，与线上不一致。

逐条打分是顺序进行的——启发式实现是纯计算，等待成本可以忽略；
将来接模型档时，慢的是模型本身，这里也不必改成并发去压上游。
"""

from __future__ import annotations

from vidrecap.data.api import PartialSummary, QualityConfig
from vidrecap.external.api import QualityScorer, SentenceCorrector
from vidrecap.monitor.evals.loader import load_corrector_cases, load_scorer_cases
from vidrecap.monitor.evals.metrics import corrector_metrics, scorer_metrics
from vidrecap.monitor.evals.schemas import (
    BaselineCheck,
    CorrectionOutcome,
    CorrectorCase,
    CorrectorMetrics,
    EvalReport,
    ScorerCase,
    ScorerMetrics,
)
from vidrecap.rules.api import (
    CORRECTOR_MIN_FIX_RATE,
    CORRECTOR_MIN_NO_HALLUCINATION_RATE,
    CORRECTOR_MIN_NO_REGRESSION_RATE,
    CORRECTOR_MIN_NOOP_SAFETY_RATE,
    SCORER_MIN_PAIRWISE_RANKING_ACCURACY,
    SCORER_MIN_THRESHOLD_ACCURACY,
    HeuristicScorer,
    check_faithfulness,
    is_acceptable,
)
from vidrecap.service.api import apply_corrections

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
    """跑 B 层考卷：先用打分器取修正前分数，再走线上编排，最后重打分并过护栏。"""
    cfg = config or QualityConfig()
    loaded = cases if cases is not None else load_corrector_cases()

    outcomes: list[CorrectionOutcome] = []
    for case in loaded:
        before = await scorer.score(case.sentence, case.context)
        processed = await apply_corrections(
            [PartialSummary(shard_index=0, summary=case.sentence)],
            {0: case.context},
            scorer,
            corrector,
            cfg,
        )
        result_text = processed[0].summary
        after = await scorer.score(result_text, case.context)
        outcomes.append(
            CorrectionOutcome(
                case_id=case.id,
                score_before=before.total,
                score_after=after.total,
                needed_fix=not is_acceptable(before, cfg),
                passed_after=is_acceptable(after, cfg),
                changed=result_text != case.sentence,
                hallucinated=check_faithfulness(result_text, case.context),
                missing_entities=[
                    entity for entity in case.gold.must_keep if entity not in result_text
                ],
            )
        )

    return corrector_metrics(outcomes)


async def run_eval(suite: str = "scorer", config: QualityConfig | None = None) -> EvalReport:
    """命令行入口用的总跑分：默认用规则层的启发式打分器与内置考卷。"""
    if suite not in AVAILABLE_SUITES:
        raise ValueError(f"未知的考卷：{suite}（可选 {', '.join(AVAILABLE_SUITES)}）")

    cfg = config or QualityConfig()
    report = EvalReport(suite=suite, threshold=cfg.threshold)

    if suite in {"scorer", "all"}:
        report.scorer = await run_scorer_eval(HeuristicScorer(cfg), None, cfg)
    if suite in {"corrector", "all"}:
        from vidrecap.external.api import DemoCorrector  # 离线替身，真实模型将来放同层

        report.corrector = await run_corrector_eval(DemoCorrector(), HeuristicScorer(cfg), None, cfg)

    return report


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

    if report.corrector is not None:
        checks.append(
            BaselineCheck(
                name="修正成功率",
                measured=report.corrector.fix_rate,
                required=CORRECTOR_MIN_FIX_RATE,
            )
        )
        checks.append(
            BaselineCheck(
                name="无幻觉率",
                measured=report.corrector.no_hallucination_rate,
                required=CORRECTOR_MIN_NO_HALLUCINATION_RATE,
            )
        )
        checks.append(
            BaselineCheck(
                name="不倒退率",
                measured=report.corrector.no_regression_rate,
                required=CORRECTOR_MIN_NO_REGRESSION_RATE,
            )
        )
        checks.append(
            BaselineCheck(
                name="好句不动率",
                measured=report.corrector.noop_safety_rate,
                required=CORRECTOR_MIN_NOOP_SAFETY_RATE,
            )
        )

    return checks
