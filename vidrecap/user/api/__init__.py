"""用户层对外窗口：其他层要"调命令行"一律从这里进。

本窗口只做转出（re-export），不写任何逻辑——命令实现住在 user/cli.py，
技能文件解析住在 user/skills.py。
"""

from vidrecap.user.cli import build_parser, main, run_demo
from vidrecap.user.skills import load_skill

__all__ = ["build_parser", "load_skill", "main", "run_demo"]
