"""监控层对外窗口：其他层要"跑评测/看成绩单"一律从这里进。

本窗口只做转出（re-export），不写任何逻辑。
带"待实现"标记的条目会在对应提交里补齐（见 docs/ROADMAP.md）。
"""

from vidrecap.monitor.evals.loader import load_corrector_cases, load_scorer_cases
from vidrecap.monitor.evals.metrics import (
    corrector_metrics,
    pairwise_ranking_accuracy,
    per_category_accuracy,
    scorer_metrics,
    scorer_misses,
    threshold_accuracy,
)
from vidrecap.monitor.evals.runner import run_corrector_eval, run_eval, run_scorer_eval
from vidrecap.monitor.evals.schemas import (
    CorrectionOutcome,
    CorrectorCase,
    CorrectorGold,
    CorrectorMetrics,
    EvalReport,
    ScorerCase,
    ScorerGold,
    ScorerMetrics,
)

__all__ = [
    "CorrectionOutcome",
    "CorrectorCase",
    "CorrectorGold",
    "CorrectorMetrics",
    "EvalReport",
    "ScorerCase",
    "ScorerGold",
    "ScorerMetrics",
    "corrector_metrics",
    "load_corrector_cases",
    "load_scorer_cases",
    "pairwise_ranking_accuracy",
    "per_category_accuracy",
    "run_corrector_eval",
    "run_eval",
    "run_scorer_eval",
    "scorer_metrics",
    "scorer_misses",
    "threshold_accuracy",
]
