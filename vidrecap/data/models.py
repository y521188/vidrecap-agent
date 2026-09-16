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


class SubtitleLine(BaseModel):
    """一条带说话人的字幕行：后台内容目录取数的基本单位。

    speaker 为空串表示"不知道谁说的"——没有人物标签的源照样能走流水线。
    """

    start: float = Field(ge=0, description="开始秒")
    end: float = Field(gt=0, description="结束秒")
    text: str
    speaker: str = ""


class SpeakerProfile(BaseModel):
    """人物档案：人物权重策略的判断依据（大咖优先、高频优先、配角过滤）。"""

    name: str
    tier: Literal["vip", "regular"] = Field(default="regular", description="vip=大咖")
    appearances: int = Field(default=0, ge=0, description="出现次数（高频优先保留）")


class SpeakerPolicyConfig(BaseModel):
    """人物权重策略的可调参数：默认值只在这里声明一次。"""

    min_share: float = Field(
        default=0.05,
        gt=0,
        le=1,
        description="常规人物台词占比低于此值视为配角过滤；大咖与无标签发言不受影响",
    )


class SpeakerPlan(BaseModel):
    """人物权重策略的产出（纯数据）：服务层照此执行，不做二次判断。"""

    keep: list[SubtitleLine] = Field(default_factory=list)
    drop: list[SubtitleLine] = Field(default_factory=list)
    dropped_speakers: list[str] = Field(default_factory=list)


class PartialSummary(BaseModel):
    """单个分片解析完成后输出的局部摘要。

    avg_quality / corrected_count 由质检回路回填；没启用打分时保持原样
    （avg_quality 为 None、corrected_count 为 0），保证老行为不受影响。
    """

    shard_index: int
    summary: str
    elapsed_sec: float = 0.0
    avg_quality: float | None = None
    corrected_count: int = 0


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
    corrected_count: int = 0
    failed_shards: int = 0
    dropped_lines: int = 0
    dropped_speakers: list[str] = Field(default_factory=list)
    avg_quality: float | None = None


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
    summarize_instruction: str = Field(
        default="概括该视频片段的场景、人物与事件",
        description="分片摘要指令，用户自定义提示词的接入点",
    )
    max_retries: int = Field(default=3, ge=0, description="LLM 调用失败后的重试次数")
    retry_initial_delay: float = Field(
        default=0.5, gt=0, description="首次重试等待秒数，之后指数退避"
    )
    retry_backoff: float = Field(default=2.0, gt=1, description="重试等待的放大系数")
    on_shard_failure: Literal["skip", "raise"] = Field(
        default="skip",
        description="重试耗尽后的失败策略：skip=跳过该分片并记入统计；raise=整个任务失败",
    )

    @model_validator(mode="after")
    def _overlap_must_be_smaller_than_shard(self) -> "PipelineConfig":
        if self.overlap_seconds >= self.shard_seconds:
            raise ValueError("overlap_seconds must be smaller than shard_seconds")
        return self


class SentenceScore(BaseModel):
    """一句话的质量评分：三个分项 + 加权总分 + 扣分原因。

    分项与总分都在 0~1 之间；reasons 记录扣分原因，供成绩单与排查使用。
    """

    sentence: str = ""
    clarity: float = Field(ge=0, le=1)
    fluency: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class QualityConfig(BaseModel):
    """质量打分与语义修正的可调参数：默认值只在本类声明一次。"""

    clarity_weight: float = Field(default=0.5, ge=0, le=1, description="清晰度权重")
    fluency_weight: float = Field(default=0.3, ge=0, le=1, description="通顺度权重")
    completeness_weight: float = Field(default=0.2, ge=0, le=1, description="完整度权重")
    threshold: float = Field(default=0.7, gt=0, le=1, description="低于此分触发修正")

    @model_validator(mode="after")
    def _weights_must_sum_to_one(self) -> "QualityConfig":
        total = self.clarity_weight + self.fluency_weight + self.completeness_weight
        if abs(total - 1.0) > 1e-6:
            raise ValueError("三个指标的权重之和必须等于 1")
        return self


class CorrectionTarget(BaseModel):
    """计划要修正的一句话。"""

    index: int
    sentence: str
    score: float
    reason: str = ""


class CorrectionPlan(BaseModel):
    """修正计划（规划层产出、服务层执行）：修哪几句、为什么。"""

    targets: list[CorrectionTarget] = Field(default_factory=list)
