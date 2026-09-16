"""考卷与成绩单的数据结构。

这些结构只在监控层内部流转（加载考卷 → 跑分 → 出成绩单），所以留在本层；
跨层共享的模型（SentenceScore、QualityConfig 等）在数据层。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 病句类别：三指标各一类，加上"多重问题"和"好句对照"
ScorerCategory = Literal["clarity", "fluency", "completeness", "mixed", "good"]


class ScorerGold(BaseModel):
    """打分器考卷的标准答案。"""

    passed: bool
    """这句话按默认阈值该不该判"过"。"""

    score_range: tuple[float, float] | None = None
    """更严的期望分数区间（可选）；不填就只校验过/不过。"""

    note: str = ""
    """出题人备注：这句话坏在哪，方便人工复核。"""


class ScorerCase(BaseModel):
    """A 层考卷的一条：一句话 + 它的原文上下文 + 标准答案。"""

    id: str
    category: ScorerCategory
    context: str
    sentence: str
    gold: ScorerGold


class CorrectorGold(BaseModel):
    """修正器考卷的标准答案。"""

    passed_after: bool = True
    """修正后是否应达到阈值。"""

    must_keep: list[str] = Field(default_factory=list)
    """必须保留的实体（少了就是修正时把事实丢了）。"""

    reference: str = ""
    """参考修正，仅供人工比对，不做字符串严格匹配。"""

    note: str = ""


class CorrectorCase(BaseModel):
    """B 层考卷的一条：烂句 + 原文 + 标准答案。"""

    id: str
    context: str
    sentence: str
    gold: CorrectorGold


class ScorerMetrics(BaseModel):
    """打分器成绩单。"""

    case_count: int
    threshold_accuracy: float
    pairwise_ranking_accuracy: float
    per_category_accuracy: dict[str, float] = Field(default_factory=dict)
    misses: list[str] = Field(default_factory=list)
    """判错的用例 id，成绩单里要能看到具体错在哪。"""


class CorrectionOutcome(BaseModel):
    """单个用例的修正结果（跑分时逐条收集，用于算指标）。"""

    case_id: str
    score_before: float
    score_after: float
    needed_fix: bool
    """修正前是否不达标——只有这类用例才谈得上"修正成功"。"""

    passed_after: bool
    """修正后是否达标。"""

    changed: bool
    """句子是否真的被改动了。"""

    hallucinated: list[str] = Field(default_factory=list)
    """护栏抠出的"原文里没有依据"的实体；非空即视为幻觉。"""

    missing_entities: list[str] = Field(default_factory=list)
    """标准答案要求保留、但结果里丢了的实体。"""


class CorrectorMetrics(BaseModel):
    """修正器成绩单。"""

    case_count: int
    fix_rate: float
    """该修的句子里，修完能达标的比例。"""

    no_hallucination_rate: float
    """没有出现幻觉实体的比例（基线要求满分）。"""

    no_regression_rate: float
    """修正后分数没有变差的比例（基线要求满分）。"""

    noop_safety_rate: float
    """本来达标的句子没被乱动的比例（基线要求满分）。"""

    misses: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    """一次跑分的总成绩单。"""

    suite: str
    """scorer / corrector / all。"""

    threshold: float
    scorer: ScorerMetrics | None = None
    corrector: CorrectorMetrics | None = None


class BaselineCheck(BaseModel):
    """一条指标与规则层基线的对照结果。"""

    name: str
    measured: float
    required: float

    @property
    def passed(self) -> bool:
        return self.measured >= self.required
