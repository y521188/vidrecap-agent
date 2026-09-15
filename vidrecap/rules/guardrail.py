"""忠实性护栏：防止修正把原文没有的东西写进摘要。

思路很朴素：把修正结果里的实体抠出来，逐个检查它在原文片段里出现过没有；
一旦发现"原文里没有的实体"，就判定为幻觉，服务层据此回退原句、不采用修正结果。

实体抽取是简化启发式（连续中文串 + 虚词白名单），属于 demo 级实现，
已知局限：分词不准时会漏判或误判。真实场景由模型判断，但**这道护栏必须在**——
宁可不改，也不能让摘要凭空多出事实。待第 3 次提交实现。
"""

from __future__ import annotations

# 这些是连接用的虚词，出现在修正结果里不算新增实体
FUNCTION_WORD_WHITELIST: frozenset[str] = frozenset(
    {
        "这个",
        "那个",
        "他们",
        "我们",
        "以及",
        "并且",
        "同时",
        "因此",
        "所以",
        "例如",
        "等等",
        "然后",
        "其中",
    }
)


def extract_entities(text: str) -> list[str]:
    """抠出文本里的实体候选：连续中文串，扣掉虚词白名单。"""
    raise NotImplementedError("待第 3 次提交实现：实体抽取")


def check_faithfulness(corrected: str, context: str) -> list[str]:
    """返回修正结果里"原文没有的实体"；返回空列表表示通过护栏。"""
    raise NotImplementedError("待第 3 次提交实现：忠实性校验")
