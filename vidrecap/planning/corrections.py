"""修正规划：哪几句要修、为什么（纯函数，不调模型）。

服务层拿着这份计划去调修正器、重打分、过护栏；遇到新情况（比如重修后
仍不达标）就回来重新要一份计划，而不是自己临时改方案。待第 3 次提交实现。

"哪句该修"用的是**规则层的达标判定**（`rules.api.unacceptable_reason`），
标准只写在规则层一处——线上判的、考卷量的、计划挑的是同一个标准。
"""

from __future__ import annotations

from vidrecap.data.api import CorrectionPlan, QualityConfig, SentenceScore


def plan_corrections(
    sentences: list[str],
    scores: list[SentenceScore],
    config: QualityConfig,
) -> CorrectionPlan:
    """挑出总分低于阈值的句子，按顺序产出修正计划。

    sentences 与 scores 一一对应；一句话都没低于阈值时返回空计划
    （空计划是合法结果，服务层据此判定"无需修正"）。
    """
    raise NotImplementedError("待第 3 次提交实现：按阈值挑出待修句子")
