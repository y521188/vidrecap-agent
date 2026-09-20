"""画面适配器（ffmpeg 可选装配）：抽帧、画面轨归并、离线演示描述。"""

from vidrecap.external.adapters.visual.describe import DemoVisionDescriber
from vidrecap.external.adapters.visual.frames import (
    VISUAL_PREFIX,
    extract_frames,
    ffmpeg_exe,
    merge_tracks,
)

__all__ = [
    "DemoVisionDescriber",
    "VISUAL_PREFIX",
    "extract_frames",
    "ffmpeg_exe",
    "merge_tracks",
]
