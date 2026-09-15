"""离线 demo：假媒体源 + 假大模型，零网络依赖跑通全流程。"""

from .llm import DemoLLM
from .source import DemoSource

__all__ = ["DemoLLM", "DemoSource"]
