"""断句：把一段文本按中文句末标点切成句子（纯函数）。

服务层拆句打分用它，所以规则只有这一份——断句一变，打分与修正就不同步了。

**注意**：外部层的 demo 适配器里有一份等价的实现（`demo/text.py`）——
按依赖规矩，适配器不准引用规划层。两份实现的一致性由
`tests/test_corrector.py` 里的对照测试守住，改动时会被立刻发现。
"""

from __future__ import annotations

import re

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？])")


def split_sentences(text: str) -> list[str]:
    """切出句子列表。

    以中文句末标点（。！？）为界，标点跟着前一句；末尾没有标点的残句也要保留——
    那往往正是"句子被截断"的信号，打分器要靠它判完整度。
    """
    return [
        sentence
        for sentence in (part.strip() for part in _SENTENCE_SPLIT_PATTERN.split(text))
        if sentence
    ]
