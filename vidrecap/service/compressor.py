"""压缩执行：按规划层的单步计划递归收敛，直到装进上下文限制。

"怎么拆、要不要放行"由规划层决定（plan_compression），
"递归、调模型、合并、兜底轮次"这些动作由本层执行。

背景：多分片局部摘要拼在一起经常超过模型上下文窗口，处理方式是工业界
标准的 map-reduce——已经装得下的内容原样返回（不花钱），装不下的对半
拆开，两边各自递归收敛，再合并；仍超限就交给模型继续压缩，直到塞进去。
"""

from __future__ import annotations

from vidrecap.external.api import LLMClient
from vidrecap.planning.api import plan_compression

_MAX_SAFETY_ROUNDS = 8


async def compress(text: str, limit: int, llm: LLMClient) -> tuple[str, int]:
    """把超过 limit 字符的文本递归压缩到限制以内。

    返回 (压缩后的文本, 发起摘要调用的次数)。limit 内的文本原样返回。
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    step = plan_compression(text, limit)
    if step.action == "pass":
        return step.left, 0

    left, left_calls = await compress(step.left, limit, llm)
    right, right_calls = await compress(step.right, limit, llm)

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
