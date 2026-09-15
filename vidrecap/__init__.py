"""vidrecap-agent: 分治式长视频概括引擎。"""

from .core.compressor import compress
from .core.models import PartialSummary, RecapResult, RecapStats, Shard
from .core.orchestrator import Orchestrator
from .core.sharder import plan_windows, shard

__version__ = "0.1.0"

__all__ = [
    "Orchestrator",
    "PartialSummary",
    "RecapResult",
    "RecapStats",
    "Shard",
    "compress",
    "plan_windows",
    "shard",
]
