"""画面适配器：ffmpeg 抽帧 + 画面轨并入字幕 + 视觉描述插座实现。

ffmpeg 是**可选装配**，解析顺序：系统 PATH 里的 ffmpeg → imageio-ffmpeg
自带的静态构建（pip 包，同样不进 vidrecap 的依赖清单）→ 都没有就报错指路。

与外挂脚本 ``scripts/video2recap.py`` 的口径一致：固定间隔抽帧、时间戳按
"序号 × 间隔"推算（fps 滤镜就是从 0 开始等间隔取）；画面行带 ``〖画面〗``
前缀、占一个短时段，与语音字幕轨按时间归并。场景切换加密抽帧见
docs/ROADMAP.md 的远期路线（PySceneDetect）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

VISUAL_PREFIX = "〖画面〗"


def ffmpeg_exe() -> str:
    """找可用的 ffmpeg：系统优先，imageio-ffmpeg 兜底，都没有就指路。"""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise RuntimeError(
            "抽帧需要 ffmpeg：装系统版，或 pip install imageio-ffmpeg"
            "（自带静态构建；按需自装，不进 vidrecap 的依赖）"
        ) from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_frames(
    video: str | Path,
    out_dir: str | Path,
    interval: float = 120.0,
    max_frames: int = 200,
) -> list[tuple[float, Path]]:
    """均匀抽帧到 out_dir，返回 [(时间戳秒, 帧文件路径)]，按时间升序。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps=1/{interval:g},scale=640:-2",
            "-frames:v",
            str(max_frames),
            "-y",
            str(out_dir / "frame_%05d.jpg"),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("抽帧失败：检查视频文件能否被 ffmpeg 读取")
    frames = sorted(out_dir.glob("frame_*.jpg"))
    return [(index * interval, path) for index, path in enumerate(frames)]


def merge_tracks(
    voice_entries: list[tuple[float, float, str]],
    visual_events: list[tuple[float, str]],
    event_seconds: float = 4.0,
) -> list[tuple[float, float, str]]:
    """画面事件并进语音字幕轨：画面行带前缀、占一个短时段，整体按时间排序。"""
    merged = list(voice_entries)
    merged.extend(
        (start, start + event_seconds, f"{VISUAL_PREFIX}{text}")
        for start, text in visual_events
    )
    return sorted(merged, key=lambda entry: entry[0])
