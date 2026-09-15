"""vidrecap-agent: 分治式长视频概括引擎。

七层结构（用户 / 服务 / 规划 / 规则 / 数据 / 外部 / 监控）的规矩见仓库根目录
AGENTS.md；本文件只是包门面，转出各层 api 窗口里常用的入口。
"""

from vidrecap.data.api import (
    PartialSummary,
    PipelineConfig,
    RecapResult,
    RecapStats,
    Shard,
)
from vidrecap.external.api import LLMClient, MediaSource
from vidrecap.service.api import Orchestrator, ProgressCallback, compress, run_recap, shard

__version__ = "0.1.0"

__all__ = [
    "LLMClient",
    "MediaSource",
    "Orchestrator",
    "PartialSummary",
    "PipelineConfig",
    "ProgressCallback",
    "RecapResult",
    "RecapStats",
    "Shard",
    "compress",
    "run_recap",
    "shard",
]
