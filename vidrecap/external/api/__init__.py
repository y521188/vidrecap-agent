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
from vidrecap.external.adapters.diarize import SherpaDiarizer, apply_speakers
from vidrecap.external.adapters.openai import OpenAICompatibleLLM
from vidrecap.external.adapters.srt import SrtSource
from vidrecap.external.adapters.visual import (
    DemoVisionDescriber,
    VISUAL_PREFIX,
    extract_frames,
    ffmpeg_exe,
    merge_tracks,
)
from vidrecap.external.adapters.whisper import WhisperTranscriber, to_srt_text
from vidrecap.external.protocols import (
    ContentCatalog,
    Diarizer,
    LLMClient,
    MediaSource,
    QualityScorer,
    SentenceCorrector,
    Transcriber,
    VisionDescriber,
)

__all__ = [
    "ContentCatalog",
    "DemoCatalog",
    "DemoCorrector",
    "DemoLLM",
    "DemoSource",
    "DemoVisionDescriber",
    "Diarizer",
    "LLMClient",
    "MediaSource",
    "OpenAICompatibleLLM",
    "QualityScorer",
    "SentenceCorrector",
    "SherpaDiarizer",
    "SrtSource",
    "Transcriber",
    "VISUAL_PREFIX",
    "VisionDescriber",
    "WhisperTranscriber",
    "apply_speakers",
    "extract_frames",
    "ffmpeg_exe",
    "merge_tracks",
    "to_srt_text",
]
