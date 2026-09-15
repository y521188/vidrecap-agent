"""用户层对外窗口：其他层要"调命令行"一律从这里进。

本窗口只做转出（re-export），不写任何逻辑——命令实现住在 user/cli.py。
"""

from vidrecap.user.cli import build_parser, main, run_demo

__all__ = ["build_parser", "main", "run_demo"]
