"""服务层对外窗口：其他层要"跑任务/执行动作"一律从这里进。

本窗口只做转出（re-export），不写任何逻辑。
ProgressCallback 回调类型也在这里挂出——它是服务层对外的承诺，
监控层与用户层按它实现回调并注入进来。
"""

from vidrecap.service.compressor import compress
from vidrecap.service.corrector import apply_corrections
from vidrecap.service.orchestrator import Orchestrator, ProgressCallback, run_recap
from vidrecap.service.sharder import shard

__all__ = [
    "Orchestrator",
    "ProgressCallback",
    "apply_corrections",
    "compress",
    "run_recap",
    "shard",
]
