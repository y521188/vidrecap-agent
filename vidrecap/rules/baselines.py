"""评测基线门槛：规则层定义的"最低可接受标准"。

CI 与成绩单用这些数值判断"这次改动有没有让质量退步"。
先把标准立在这里，再写实现——数值在第 2、3 次提交出题之后按首次实测校准。
"""

from __future__ import annotations

# --- 打分器（A 层考卷，第 2 次提交）---
SCORER_MIN_THRESHOLD_ACCURACY = 0.75
"""判"过/不过"与标准答案一致的比例下限。"""

SCORER_MIN_PAIRWISE_RANKING_ACCURACY = 0.90
"""（好句, 坏句）两两配对中，好句分数更高的比例下限。"""

# --- 修正器（B 层考卷，第 3 次提交）---
CORRECTOR_MIN_FIX_RATE = 0.80
"""修正后重新打分能过阈值的比例下限。"""

CORRECTOR_MIN_NO_HALLUCINATION_RATE = 1.00
"""不留幻觉的比例下限——由护栏保证，必须是满分。"""

CORRECTOR_MIN_NO_REGRESSION_RATE = 1.00
"""不把句子改得更差的比例下限——越改越糟还不如不改。"""
