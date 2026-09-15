"""数据层：全项目的数据模型、计划对象与可调参数。

本层只描述"数据长什么样"，不含任何行为——分片、摘要、统计、计划、
流水线配置都定义在这里，其他层通过本层窗口取用。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class CompressionStep(BaseModel):
    """压缩的单步计划（规划层产出、服务层执行）。

    装得下就是 action="pass"（left 为原文，不产生模型调用）；
    装不下就是 action="split"，left/right 是拆开后的两段。
    """

    action: Literal["pass", "split"]
    left: str = ""
    right: str = ""


class PipelineConfig(BaseModel):
    """一次概括任务的全部可调参数：默认值只在本类声明一次。

    服务层和规则层消费本对象，用户层（命令行、将来的服务化接口）只做覆盖，
    避免同一个数字在多处各写一遍。
    """

    shard_seconds: float = Field(default=600.0, gt=0, description="分片责任区时长（秒）")
    overlap_seconds: float = Field(default=30.0, ge=0, description="前后重叠缓冲区（秒）")
    max_concurrency: int = Field(default=8, gt=0, description="并行分片数上限")
    context_limit: int = Field(default=4000, gt=0, description="上下文字符上限")
    incremental_at: float = Field(
        default=0.8, gt=0, le=1.0, description="增量摘要触发进度（0~1）"
    )

    @model_validator(mode="after")
    def _overlap_must_be_smaller_than_shard(self) -> "PipelineConfig":
        if self.overlap_seconds >= self.shard_seconds:
            raise ValueError("overlap_seconds must be smaller than shard_seconds")
        return self
