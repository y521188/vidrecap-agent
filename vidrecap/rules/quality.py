"""质量打分器：按清晰度 / 通顺度 / 完整度给一句话打分。

三块规则（待第 1 次提交实现）：

- **清晰度**：主语是否在场（缺主语只留谓语就是"谁干的"不明）、
  指代词密度（"他/她/它/这个/那个"堆多了就指不明白）；
- **通顺度**：相邻字词重复（"介绍介绍了"）、标点与断句异常、
  句长异常（过短像碎片、过长像没断句的连读）；
- **完整度**：是否被截断、句子结构是否成型。

完整度只查"句子本身完不完整"，**不查**"有没有覆盖原文的全部信息"——
概括本来就该丢细节，用覆盖率当标准会误伤好句；补信息的活交给修正器。

本层是纯判断：不调模型、不读时钟、不用随机（由 tests/test_layering.py 强制）。
评分模型 SentenceScore 与权重阈值模型 QualityConfig 都在数据层。
"""

from __future__ import annotations

from vidrecap.data.api import QualityConfig, SentenceScore


class HeuristicScorer:
    """启发式打分器：零依赖、确定性、可离线复现。

    形状对齐外部层 QualityScorer 插座（方法签名一致即可，不需要继承）。
    真实模型的打分器将来放进 external/adapters/，同一套考卷上比分数。
    """

    def __init__(self, config: QualityConfig | None = None) -> None:
        raise NotImplementedError("待第 1 次提交实现：三指标启发式打分器")

    async def score(self, sentence: str, context: str) -> SentenceScore:
        """给一句话打分：三个分项各 0~1，按权重加权得总分。

        异步只是为了对齐插座形状（模型档实现要 await 线程池），
        这里全是同步纯计算，不引入任何等待。
        """
        raise NotImplementedError("待第 1 次提交实现：三指标启发式打分器")
