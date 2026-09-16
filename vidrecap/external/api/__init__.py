"""外部层对外窗口：插座协议与内置适配器都从这里进。

本窗口只做转出（re-export），不写任何逻辑——协议类定义住在
external/protocols.py，不在窗口里。
"""

from vidrecap.external.adapters.demo import (
    DemoCatalog,
    DemoCorrector,
    DemoLLM,
    DemoSource,
)
from vidrecap.external.adapters.openai import OpenAICompatibleLLM
from vidrecap.external.adapters.srt import SrtSource
from vidrecap.external.protocols import (
    ContentCatalog,
    LLMClient,
    MediaSource,
    QualityScorer,
    SentenceCorrector,
)

__all__ = [
    "ContentCatalog",
    "DemoCatalog",
    "DemoCorrector",
    "DemoLLM",
    "DemoSource",
    "LLMClient",
    "MediaSource",
    "OpenAICompatibleLLM",
    "QualityScorer",
    "SentenceCorrector",
    "SrtSource",
]
