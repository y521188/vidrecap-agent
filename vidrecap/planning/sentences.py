"""断句：把一段文本按中文句末标点切成句子（纯函数）。

服务层拆句打分、demo 假模型抽句都复用它，避免两处各写一套断句规则
（断句一变，打分与摘要就不同步了）。待第 3 次提交实现。
"""

from __future__ import annotations


def split_sentences(text: str) -> list[str]:
    """切出句子列表。

    以中文句末标点（。！？）为界；末尾没有标点的残句也要保留——
    那往往正是"句子被截断"的信号，打分器要靠它判完整度。
    """
    raise NotImplementedError("待第 3 次提交实现：共享断句纯函数")
