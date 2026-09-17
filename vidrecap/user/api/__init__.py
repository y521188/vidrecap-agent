"""用户层对外窗口：其他层要"调命令行/起服务"一律从这里进。

本窗口只做转出（re-export），不写任何逻辑——命令实现住在 user/cli.py，
技能文件解析住在 user/skills.py，HTTP 服务住在 user/server/。
"""

from vidrecap.user.cli import build_parser, main, run_demo
from vidrecap.user.server import RecapRequest, build_server, serve
from vidrecap.user.skills import load_skill

__all__ = [
    "RecapRequest",
    "build_parser",
    "build_server",
    "load_skill",
    "main",
    "run_demo",
    "serve",
]
