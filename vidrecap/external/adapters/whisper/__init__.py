"""faster-whisper 适配器（可选依赖）：视频/音频 → 字幕。"""

from vidrecap.external.adapters.whisper.transcribe import (
    WhisperTranscriber,
    to_srt_text,
)

__all__ = ["WhisperTranscriber", "to_srt_text"]
