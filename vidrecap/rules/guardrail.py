"""忠实性护栏：防止修正把原文没有的东西写进摘要。

思路分两步：

1. 从修正结果里抠出**实体候选**（连续中文串、数字），
2. 逐个检查它在原文片段里有没有依据；没有依据的即为幻觉。

"有没有依据"不是简单的是否包含子串——合法改写常常换断句、换语序
（"他没来开会" → "他缺席了会议"），字面比对会把它们误判成幻觉。
所以对包含不上的实体，再退一步检查它能否**由原文的片段拼出来**：
拼得出就算有依据，拼不出才判越界。

已知局限：这是 demo 级启发式，对同义改写（原文"缺席"、修正写"没到场"）
仍然会误判；宁严勿松是有意的——**宁可回退原句，也不能让摘要凭空多出事实**。
真实场景应换成模型判断（见 docs/REUSE.md），但机制上这道护栏必须在。
"""

from __future__ import annotations

import re
from functools import lru_cache

# 这些是连接用的虚词：修正时补上它们不算新增事实
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
        "此外",
        "另外",
        "不过",
        "但是",
        "而且",
        "如果",
        "因为",
        "可以",
        "已经",
        "随后",
        "最后",
        "首先",
        "其次",
        "现场",
    }
)

# 实体候选：两个以上连续汉字，或数字（含小数与百分号）
_ENTITY_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?%?")

# 拼接核对时用的片段长度上限：比这更长的连续片段不可能是单个实体
_MAX_FRAGMENT_CHARS = 8

# 这些连接字本身不是事实：改写时补个"并""与"不算新增内容，核对时跳过
_CONNECTIVE_CHARS = "的了在与和就都也才吗呢着过并而且但又还或既从把被向"


def extract_entities(text: str) -> list[str]:
    """抠出文本里的实体候选：连续中文串与数字，掐头去尾的连接字、虚词白名单都不要。

    只做"候选"——实体是否有依据由 :func:`check_faithfulness` 判断。
    """
    candidates = []
    for item in _ENTITY_PATTERN.findall(text):
        cleaned = item.strip(_CONNECTIVE_CHARS)
        if len(cleaned) >= 2 and cleaned not in FUNCTION_WORD_WHITELIST:
            candidates.append(cleaned)
    return candidates


@lru_cache(maxsize=16)
def _context_fragments(context: str) -> set[str]:
    """原文里所有 2~8 字的片段，用于判断"能否拼出来"。

    结果只取决于 context，因此缓存不破坏纯函数性质；
    同一片段里几十句话共用一份原文，缓存能省下大量重复构造。
    """
    fragments: set[str] = set()
    for length in range(2, _MAX_FRAGMENT_CHARS + 1):
        fragments.update(
            context[i : i + length] for i in range(max(0, len(context) - length + 1))
        )
    return fragments


def _can_be_composed(entity: str, fragments: set[str]) -> bool:
    """这个实体能否几乎完全由原文片段拼出来（应对换断句、换语序的合法改写）。

    连接字不需要依据，直接跳过；至多容忍一个对不上的字——
    那多半是分词边界问题，两个以上对不上就是真捏造了新内容。
    ponytail: 一字容差的 ceilings 是同音异写（"缺席"改"没到场"）仍会误判，
    要堵住得换句级语义核对（模型档，见 docs/REUSE.md）。
    """
    index = 0
    unmatched = 0
    while index < len(entity):
        if entity[index] in _CONNECTIVE_CHARS:
            index += 1
            continue
        matched = 0
        for length in range(min(_MAX_FRAGMENT_CHARS, len(entity) - index), 1, -1):
            if entity[index : index + length] in fragments:
                matched = length
                break
        if matched == 0:
            unmatched += 1
            if unmatched > 1:
                return False
            index += 1
            continue
        index += matched
    return True


def check_faithfulness(corrected: str, context: str) -> list[str]:
    """返回修正结果里"原文没有依据"的实体；返回空列表表示通过护栏。"""
    if not context:
        return extract_entities(corrected)

    fragments = _context_fragments(context)
    violations: list[str] = []
    for entity in extract_entities(corrected):
        if entity in context:
            continue
        if _can_be_composed(entity, fragments):
            continue
        violations.append(entity)
    return violations
