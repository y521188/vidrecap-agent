"""能力抽象：核心引擎只认接口，不绑定任何厂商。

真实的大模型客户端、多模态识别服务、OCR 服务都通过实现这两个
Protocol 接入，demo 里的是离线假实现。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


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
