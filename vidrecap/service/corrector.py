"""修正执行：按计划调修正器、重打分、过护栏、不合格回退原句。

完整流程（待第 3 次提交实现）：

1. 用规划层的 `split_sentences` 把每段摘要拆成句子；
2. 逐句调打分器（规则层的标准）得到 `SentenceScore`；
3. 向规划层要修正计划 `plan_corrections`；
4. 按计划调用修正器（外部层插座），对修正结果重新打分；
5. 用规则层的护栏检查忠实性——**没过护栏、或者分数没变好，一律回退原句**，
   宁可保留原样，也不接受"改出新事实"或"越改越糟"；
6. 重组摘要，记录平均质量分与修正条数，回填进 PartialSummary。

本层只执行、不发明策略：阈值与权重的默认值在数据层的 QualityConfig，
"该修哪几句"由规划层决定。
"""

from __future__ import annotations

from vidrecap.data.api import PartialSummary, QualityConfig
from vidrecap.external.api import QualityScorer, SentenceCorrector


async def apply_corrections(
    partials: list[PartialSummary],
    context_by_shard: dict[int, str],
    scorer: QualityScorer,
    corrector: SentenceCorrector,
    config: QualityConfig | None = None,
) -> list[PartialSummary]:
    """对局部摘要做"按句打分 → 低分修正 → 重打分 → 护栏"的处理。

    context_by_shard 是分片序号到该片段原文的映射，既用于打分（判断句子
    是否缺失信息），也用于护栏（判断修正是否引入了原文没有的实体）。
    返回更新后的 partials（修正后的摘要、平均分、修正条数）。
    """
    raise NotImplementedError("待第 3 次提交实现：按句打分与修正编排")
