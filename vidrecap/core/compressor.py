"""二分递归压缩：拼接结果超上下文限制时，对半拆分、下沉递归精简。

多分片局部摘要拼在一起经常超过模型上下文窗口。处理方式是工业界
标准的 map-reduce：已经装得下的内容原样返回（不花钱），装不下的
对半拆开，两边各自递归收敛，再合并；仍超限就把合并结果交给模型
继续压缩，直到塞进去为止。
"""

from __future__ import annotations

from .protocols import LLMClient

_MAX_SAFETY_ROUNDS = 8


def _split_in_half(text: str) -> tuple[str, str]:
    """优先按空行段落对半拆（保语义完整），没有段落结构再按字符硬拆。"""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) >= 2:
        mid = len(paragraphs) // 2
        return "\n\n".join(paragraphs[:mid]), "\n\n".join(paragraphs[mid:])
    mid = len(text) // 2
    return text[:mid], text[mid:]


async def compress(text: str, limit: int, llm: LLMClient) -> tuple[str, int]:
    """把超过 limit 字符的文本递归压缩到限制以内。

    返回 (压缩后的文本, 发起摘要调用的次数)。limit 内的文本原样返回。
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    if len(text) <= limit:
        return text, 0

    left, right = _split_in_half(text)
    left, left_calls = await compress(left, limit, llm)
    right, right_calls = await compress(right, limit, llm)

    merged = left + "\n\n" + right
    if len(merged) <= limit:
        return merged, left_calls + right_calls

    summarized = merged
    calls = left_calls + right_calls
    for _ in range(_MAX_SAFETY_ROUNDS):
        summarized = await llm.summarize(
            summarized, instruction="合并并精简以下内容：保留关键信息，去除重复"
        )
        calls += 1
        if len(summarized) <= limit:
            return summarized, calls
    raise RuntimeError(
        f"compression failed to converge after {_MAX_SAFETY_ROUNDS} summarization rounds"
    )
