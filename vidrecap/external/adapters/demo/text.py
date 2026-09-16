"""demo 适配器共用的断句。

规划层有一份等价实现（`planning/sentences.py`），但按依赖规矩，
外部层不准引用规划层，所以这里保留一份副本。
两份的一致性由 `tests/test_corrector.py` 的对照测试守住——改了这边忘了改那边，测试会红。
"""

from __future__ import annotations

import re

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？])")


def split_sentences(text: str) -> list[str]:
    """按中文句末标点断句，标点跟着前一句；保留末尾没有标点的残句。"""
    return [
        sentence
        for sentence in (part.strip() for part in _SENTENCE_SPLIT_PATTERN.split(text))
        if sentence
    ]
