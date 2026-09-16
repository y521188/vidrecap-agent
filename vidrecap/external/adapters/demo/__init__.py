"""离线 demo：假媒体源 + 假大模型 + 假修正器 + 假后台目录，零网络依赖跑通全流程。"""

from vidrecap.external.adapters.demo.backend import DemoCatalog
from vidrecap.external.adapters.demo.corrector import DemoCorrector
from vidrecap.external.adapters.demo.llm import DemoLLM
from vidrecap.external.adapters.demo.source import DemoSource

__all__ = ["DemoCatalog", "DemoCorrector", "DemoLLM", "DemoSource"]
