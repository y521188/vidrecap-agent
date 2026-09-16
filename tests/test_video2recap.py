"""外挂脚本测试：SRT 时间轴格式、字幕生成、轨道合并、参数转交、与包的接口对账。

语音识别本体不在测试范围（要下模型、跑音频）；抽帧测试需要 ffmpeg，
没装就跳过（CI 的 Ubuntu 自带）。
"""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "video2recap.py"
_spec = importlib.util.spec_from_file_location("video2recap", _SCRIPT)
video2recap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(video2recap)


def test_srt_timestamp_format():
    assert video2recap._ts(0) == "00:00:00,000"
    assert video2recap._ts(1.5) == "00:00:01,500"
    assert video2recap._ts(3661.25) == "01:01:01,250"
    assert video2recap._ts(7225.678) == "02:00:25,678"


def test_write_srt_skips_empty_and_keeps_numbering_continuous(tmp_path):
    path = tmp_path / "out.srt"
    video2recap.write_srt(
        [
            (0.0, 2.0, " 你好。 "),
            (2.0, 4.0, "   "),  # 空段跳过，序号不断号
            (4.0, 9.2, "第二句。"),
        ],
        path,
    )
    assert path.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:02,000\n你好。\n\n"
        "2\n00:00:04,000 --> 00:00:09,200\n第二句。\n"
    )


def test_unknown_args_are_forwarded_to_vidrecap():
    args, forwarded = video2recap.build_parser().parse_known_args(
        ["a.mp4", "--llm", "openai", "--model", "x", "--whisper-model", "tiny"]
    )
    assert args.video == "a.mp4"
    assert args.whisper_model == "tiny"
    assert forwarded == ["--llm", "openai", "--model", "x"]


def test_script_output_feeds_srt_source_directly(tmp_path):
    """脚本产出的 SRT 必须能被 SrtSource 原样吃下——外挂与包的接口对账。"""
    from vidrecap.external.api import SrtSource

    path = tmp_path / "round.srt"
    video2recap.write_srt([(0.5, 4.0, "大家好。"), (4.0, 9.2, "开始正题。")], path)
    source = SrtSource(path)
    assert source.duration() == 9.2
    assert "大家好" in source.content(0, 5)


def test_merge_tracks_interleaves_visual_events_by_time():
    voice = [(0.0, 4.0, "大家好。"), (30.0, 34.0, "开始正题。")]
    merged = video2recap.merge_tracks(voice, [(12.0, "主讲人翻到第二页")])
    assert merged == [
        (0.0, 4.0, "大家好。"),
        (12.0, 16.0, "〖画面〗主讲人翻到第二页"),
        (30.0, 34.0, "开始正题。"),
    ]


def test_visual_flags_defaults_and_forwarding():
    args, forwarded = video2recap.build_parser().parse_known_args(
        ["a.mp4", "--visual", "--max-frames", "5", "--llm", "openai"]
    )
    assert args.visual is True
    assert args.max_frames == 5
    assert args.frame_interval == 120.0  # 默认稀疏，成本上限明确
    assert forwarded == ["--llm", "openai"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg（CI 自带，本机可能没有）")
def test_pick_frames_extracts_evenly_spaced_frames(tmp_path):
    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=6:size=160x120:rate=5",
            "-pix_fmt", "yuv420p", "-y", str(video),
        ],
        check=True,
    )
    frames = video2recap.pick_frames(str(video), tmp_path / "frames", interval=2.0, max_frames=3)
    assert [timestamp for timestamp, _ in frames] == [0.0, 2.0, 4.0]
    assert all(path.exists() for _, path in frames)
