"""假大模型：抽取式"摘要"，确定性输出，用来离线验证调度与压缩逻辑。

抽取规则：隔句采样后截断到原文的约 1/3，保证每次调用都能稳定缩短
文本，让二分递归压缩在 demo 里真实触发。
"""

from __future__ import annotations

import re

_SPLIT_RE = re.compile(r"(?<=[。！？])")


class DemoLLM:
    """实现 core.protocols.LLMClient 接口的离线替身。"""

    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, text: str, instruction: str = "") -> str:
        self.calls += 1
        sentences = [s for s in (p.strip() for p in _SPLIT_RE.split(text)) if s]
        kept = sentences[::2] if len(sentences) > 4 else sentences
        summary = "".join(kept)
        cap = max(60, min(len(text) // 3, 400))
        return summary[:cap]
