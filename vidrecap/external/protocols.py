"""能力抽象（插座）：核心引擎只认接口，不绑定任何厂商。

真实的大模型客户端、多模态识别服务、OCR 服务、质量打分器、句子修正器
都通过实现这里的 Protocol 接入，demo 里的是离线假实现。

实现方**不需要 import 本模块**——形状（方法签名）对得上即可，
一致性由测试用 runtime_checkable 的 isinstance 验证。
这样"规则层只依赖数据层"这条简单规矩才保得住。

本模块属于外部层实现部分（窗口在 external/api/），因为它包含类定义，
而 api 窗口只允许放转出语句。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vidrecap.data.api import SentenceScore


@runtime_checkable
class LLMClient(Protocol):
    """大模型客户端的最小接口：给它一段文本，还你一份摘要。"""

    async def summarize(self, text: str, instruction: str = "") -> str: ...


@runtime_checkable
class MediaSource(Protocol):
    """媒体内容来源：给它一个时间段，返回该段的文本内容。

    真实实现对接多模态识别 + OCR 字幕；接口只关心"这段时间里说了什么"。
    """

    def duration(self) -> float: ...

    def content(self, start: float, end: float) -> str: ...


@runtime_checkable
class QualityScorer(Protocol):
    """质量打分：给一句话和它所在片段的原文，还一个三指标评分。

    必须是同步、确定性的纯判断——不调模型、不读时钟，同样输入永远同样输出，
    否则评测集失去意义。当前实现是规则层的启发式打分器，将来可换模型实现。
    """

    def score(self, sentence: str, context: str) -> SentenceScore: ...


@runtime_checkable
class SentenceCorrector(Protocol):
    """句子修正：给一句低于阈值的句子和它的原文，还一句改好的话。

    修正只许"补充与理顺"，不许引入原文没有的事实——是否越界由规则层的
    忠实性护栏判定，服务层据此决定采用还是回退原句。
    """

    async def correct(self, sentence: str, context: str) -> str: ...
