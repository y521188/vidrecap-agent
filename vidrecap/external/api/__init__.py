"""外部层对外窗口：插座协议与内置适配器都从这里进。

本窗口只做转出（re-export），不写任何逻辑——协议类定义住在
external/protocols.py，不在窗口里。
"""

from vidrecap.external.adapters.demo import DemoCorrector, DemoLLM, DemoSource
from vidrecap.external.adapters.srt import SrtSource
from vidrecap.external.protocols import (
    LLMClient,
    MediaSource,
    QualityScorer,
    SentenceCorrector,
)

__all__ = [
    "DemoCorrector",
    "DemoLLM",
    "DemoSource",
    "LLMClient",
    "MediaSource",
    "QualityScorer",
    "SentenceCorrector",
    "SrtSource",
]
