"""离线 demo：假媒体源 + 假大模型，零网络依赖跑通全流程。"""

from vidrecap.external.adapters.demo.llm import DemoLLM
from vidrecap.external.adapters.demo.source import DemoSource

__all__ = ["DemoLLM", "DemoSource"]
