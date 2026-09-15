"""数据模型：分片、局部摘要、最终结果。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Shard(BaseModel):
    """一个时间分片。

    core_start/core_end 是该分片独占的"责任区"，互不重叠；
    buffered_start/buffered_end 是向前后各扩了重叠缓冲区的实际取材范围，
    text 是缓冲区范围内的内容文本（相邻分片会有部分重复，这是刻意设计）。
    """

    index: int
    core_start: float
    core_end: float
    buffered_start: float
    buffered_end: float
    text: str = ""


class PartialSummary(BaseModel):
    """单个分片解析完成后输出的局部摘要。"""

    shard_index: int
    summary: str
    elapsed_sec: float = 0.0


class RecapStats(BaseModel):
    duration_sec: float
    shard_count: int
    shard_seconds: float
    overlap_seconds: float
    partial_count: int
    compression_rounds: int = 0
    incremental_at: float
    chars_in: int = 0
    chars_out: int = 0


class RecapResult(BaseModel):
    """一次完整概括任务的产出。"""

    recap: str
    partials: list[PartialSummary] = Field(default_factory=list)
    incremental_recap: str | None = None
    stats: RecapStats
