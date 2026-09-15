"""假修正器：确定性、抽取式的"修正"，用来离线验证修正编排与护栏。

做法（待第 4 次提交实现）：只从原文里找现成的句子拼回去，不改写、不新造内容，
因此天然不会产生幻觉。它的用途是验证"编排流程正确"，不代表真实大模型的修正能力——
真实能力要靠同一套考卷跑真实适配器来对比。
"""

from __future__ import annotations


class DemoCorrector:
    """实现外部层 SentenceCorrector 插座的离线替身。"""

    def __init__(self) -> None:
        self.calls = 0

    async def correct(self, sentence: str, context: str) -> str:
        """从原文里抽出包含缺失信息的那句话返回。"""
        raise NotImplementedError("待第 4 次提交实现：抽取式确定性修正器")
