"""评测基线门槛：规则层定义的"最低可接受标准"。

CI 与 `vidrecap eval` 用这些数值判断"这次改动有没有让质量退步"。
数值按首次实测校准（只上调不下调），并留出少量余量：
门槛定成满分会让规则的小改动一动就红，反而促使别人去改考卷而不是改实现。
"""

from __future__ import annotations

# --- 打分器（A 层考卷 scorer_v1，49 条）---
# 首次实测：阈值准确率 49/49、排序正确率 100%，故从初值 0.75 / 0.90 上调。
SCORER_MIN_THRESHOLD_ACCURACY = 0.95
"""判"过/不过"与标准答案一致的比例下限。"""

SCORER_MIN_PAIRWISE_RANKING_ACCURACY = 0.95
"""（好句, 坏句）两两配对中，好句分数更高的比例下限。"""

# --- 修正器（B 层考卷，待第 3 次提交出题后校准）---
CORRECTOR_MIN_FIX_RATE = 0.80
"""修正后重新打分能过阈值的比例下限。"""

CORRECTOR_MIN_NO_HALLUCINATION_RATE = 1.00
"""不留幻觉的比例下限——由护栏保证，必须是满分。"""

CORRECTOR_MIN_NO_REGRESSION_RATE = 1.00
"""不把句子改得更差的比例下限——越改越糟还不如不改。"""
