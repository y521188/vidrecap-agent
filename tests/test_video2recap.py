"""外挂脚本测试：SRT 时间轴格式、字幕文件生成、参数转交切分、与包的接口对账。

语音识别本体不在测试范围（要下模型、跑音频）——脚本可离线验证的纯逻辑就这些。
"""

import importlib.util
from pathlib import Path

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
