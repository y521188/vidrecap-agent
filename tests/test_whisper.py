"""faster-whisper 适配器测试：SRT 格式纯函数与插座形状（不加载真模型）。"""

from vidrecap.external.api import Transcriber, WhisperTranscriber, to_srt_text


def test_to_srt_text_formats_timestamps_and_skips_empty():
    entries = [
        (0.0, 2.5, " 张伟介绍了产品。 "),
        (2.5, 4.0, "   "),  # 空段：跳过但序号不能断
        (4.0, 61.234, "他演示了场景。"),
    ]
    lines = to_srt_text(entries).splitlines()
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:02,500"
    assert lines[2] == "张伟介绍了产品。"
    assert lines[4] == "2"  # 空段跳过后序号连续
    assert lines[5] == "00:00:04,000 --> 00:01:01,234"


def test_whisper_transcriber_satisfies_protocol():
    """形状对上即可（无需继承）——一致性靠 runtime_checkable 的 isinstance。"""
    assert isinstance(WhisperTranscriber(), Transcriber)
