"""规则层对外窗口：其他层要"标准"一律从这里进。

本窗口只做转出（re-export），不写任何逻辑。
"""

from vidrecap.rules.baselines import (
    CORRECTOR_MIN_FIX_RATE,
    CORRECTOR_MIN_NO_HALLUCINATION_RATE,
    CORRECTOR_MIN_NO_REGRESSION_RATE,
    SCORER_MIN_PAIRWISE_RANKING_ACCURACY,
    SCORER_MIN_THRESHOLD_ACCURACY,
)
from vidrecap.rules.guardrail import check_faithfulness, extract_entities
from vidrecap.rules.quality import (
    SEVERE_METRIC_FLOOR,
    HeuristicScorer,
    is_acceptable,
    unacceptable_reason,
)

__all__ = [
    "CORRECTOR_MIN_FIX_RATE",
    "CORRECTOR_MIN_NO_HALLUCINATION_RATE",
    "CORRECTOR_MIN_NO_REGRESSION_RATE",
    "SEVERE_METRIC_FLOOR",
    "SCORER_MIN_PAIRWISE_RANKING_ACCURACY",
    "SCORER_MIN_THRESHOLD_ACCURACY",
    "HeuristicScorer",
    "check_faithfulness",
    "extract_entities",
    "is_acceptable",
    "unacceptable_reason",
]
