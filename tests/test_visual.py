"""画面适配器测试：归并纯函数、演示描述器、ffmpeg 解析与真实抽帧（有 ffmpeg 才跑）。"""

import asyncio
import subprocess
import sys

import pytest

from vidrecap.external.adapters.visual import frames as frames_module
from vidrecap.external.api import (
    DemoVisionDescriber,
    OpenAICompatibleLLM,
    VISUAL_PREFIX,
    VisionDescriber,
    extract_frames,
    ffmpeg_exe,
    merge_tracks,
)


def _ffmpeg_available() -> bool:
    try:
        ffmpeg_exe()
        return True
    except RuntimeError:
        return False


def test_merge_tracks_orders_and_prefixes_visual_events():
    voice = [(2.0, 4.0, "张伟介绍了产品。")]
    visual = [(0.0, "开场画面：城市夜景。"), (5.0, "结尾画面：产品特写。")]
    merged = merge_tracks(voice, visual, event_seconds=4.0)
    assert [entry[0] for entry in merged] == [0.0, 2.0, 5.0]  # 按时间归并
    assert merged[0][2] == f"{VISUAL_PREFIX}开场画面：城市夜景。"
    assert merged[0][1] == 4.0  # 画面事件占一个短时段
    assert merged[1][2] == "张伟介绍了产品。"  # 语音行原样保留


def test_demo_vision_describer_is_deterministic_and_labeled():
    describer = DemoVisionDescriber()
    first = asyncio.run(describer.describe_image(b"fake-bytes", "描述这张图"))
    second = asyncio.run(describer.describe_image(b"fake-bytes", "描述这张图"))
    assert first == second and first  # 同输入永远同输出（确定性铁律）
    assert "离线演示" in first  # 明确标注，不冒充真实画面理解


def test_vision_protocol_shapes():
    assert isinstance(DemoVisionDescriber(), VisionDescriber)
    assert isinstance(OpenAICompatibleLLM(model="m"), VisionDescriber)


def test_ffmpeg_exe_reports_instructions_when_absent(monkeypatch):
    monkeypatch.setattr(frames_module.shutil, "which", lambda _: None)
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)  # None 会让 import 失败
    with pytest.raises(RuntimeError, match="ffmpeg"):
        ffmpeg_exe()


@pytest.mark.skipif(not _ffmpeg_available(), reason="没有 ffmpeg / imageio-ffmpeg 时跳过真实抽帧")
def test_extract_frames_from_generated_video(tmp_path):
    video = tmp_path / "clip.mp4"
    made = subprocess.run(
        [
            ffmpeg_exe(),
            "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
            "-y", str(video),
        ],
        check=False,
    )
    assert made.returncode == 0, "生成测试视频失败"
    frames = extract_frames(video, tmp_path / "frames", interval=1.0, max_frames=3)
    assert [round(ts) for ts, _ in frames] == [0, 1, 2]
    assert all(path.exists() for _, path in frames)
