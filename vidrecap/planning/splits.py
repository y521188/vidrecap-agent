"""压缩规划：一次只做一个决定——放行，还是对半拆开。

服务层拿着这个决定去干活（递归、调模型），遇到新情况再回来要下一步计划。
规划层自己不做递归、不调用模型，"怎么拆"和"谁来拆"因此彻底分开。
"""

from __future__ import annotations

from vidrecap.data.api import CompressionStep


def _split_in_half(text: str) -> tuple[str, str]:
    """优先按空行段落对半拆（保语义完整），没有段落结构再按字符硬拆。"""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) >= 2:
        mid = len(paragraphs) // 2
        return "\n\n".join(paragraphs[:mid]), "\n\n".join(paragraphs[mid:])
    mid = len(text) // 2
    return text[:mid], text[mid:]


def plan_compression(text: str, limit: int) -> CompressionStep:
    """给出压缩的单步计划：装得下就原样放行，装不下就对半拆开。"""
    if len(text) <= limit:
        return CompressionStep(action="pass", left=text)
    left, right = _split_in_half(text)
    return CompressionStep(action="split", left=left, right=right)
