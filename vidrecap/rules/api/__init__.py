"""规则层对外窗口：其他层要"标准"一律从这里进。

本窗口只做转出（re-export），不写任何逻辑。
带"待实现"标记的条目会在对应提交里补齐（见 docs/ROADMAP.md）。
"""

from vidrecap.rules.baselines import (
    CORRECTOR_MIN_FIX_RATE,
    CORRECTOR_MIN_NO_HALLUCINATION_RATE,
    CORRECTOR_MIN_NO_REGRESSION_RATE,
    SCORER_MIN_PAIRWISE_RANKING_ACCURACY,
    SCORER_MIN_THRESHOLD_ACCURACY,
)
from vidrecap.rules.guardrail import check_faithfulness, extract_entities
from vidrecap.rules.quality import HeuristicScorer

__all__ = [
    "CORRECTOR_MIN_FIX_RATE",
    "CORRECTOR_MIN_NO_HALLUCINATION_RATE",
    "CORRECTOR_MIN_NO_REGRESSION_RATE",
    "HeuristicScorer",
    "SCORER_MIN_PAIRWISE_RANKING_ACCURACY",
    "SCORER_MIN_THRESHOLD_ACCURACY",
    "check_faithfulness",
    "extract_entities",
]
