"""假修正器：确定性、抽取式的"修正"，用来离线验证修正编排与护栏。

做法：从原文里挑一句**与待修句最像的现成句子**原样返回（相似度用标准库的
序列比对算，同分取靠前的那句，因此完全确定性）。它不改写、不新造内容，
所以天然不会产生幻觉。

**它不代表真实大模型的修正能力**——它的用途只是让"打分 → 计划 → 修正 →
重打分 → 护栏 → 回退"这条编排在离线环境里能被真实跑通。真实修正能力要靠
同一套考卷跑真实适配器来对比。
"""

from __future__ import annotations

from difflib import SequenceMatcher

from vidrecap.external.adapters.demo.text import split_sentences


class DemoCorrector:
    """实现外部层 SentenceCorrector 插座的离线替身。"""

    def __init__(self) -> None:
        self.calls = 0

    async def correct(self, sentence: str, context: str) -> str:
        """从原文里抽出与待修句最相似的那句话。"""
        self.calls += 1
        candidates = split_sentences(context)
        if not candidates:
            return sentence

        best = max(
            candidates,
            key=lambda candidate: (
                SequenceMatcher(None, sentence, candidate).ratio(),
                -candidates.index(candidate),
            ),
        )
        return best
