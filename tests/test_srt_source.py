"""SRT 字幕源测试：解析口径、时间窗对齐、重叠取样、容错与确定性。"""

import pytest

from vidrecap.external.adapters.srt import parse_srt
from vidrecap.external.api import MediaSource, SrtSource
from vidrecap.user.api import main

_SAMPLE = """\
1
00:00:00,500 --> 00:00:04,000
大家好，欢迎收看本期节目。

2
00:00:04,000 --> 00:00:09,200
今天我们聊聊
媒体融合的新趋势。

00:00:09,200 --> 00:00:12,000
首先从案例说起。
"""


def _write(tmp_path) -> SrtSource:
    path = tmp_path / "sample.srt"
    path.write_text(_SAMPLE, encoding="utf-8")
    return SrtSource(path)


def test_parse_reads_timestamps_with_or_without_sequence_numbers():
    entries = parse_srt(_SAMPLE)
    assert [(round(b, 3), round(e, 3), body) for b, e, body in entries] == [
        (0.5, 4.0, "大家好，欢迎收看本期节目。"),
        (4.0, 9.2, "今天我们聊聊媒体融合的新趋势。"),
        (9.2, 12.0, "首先从案例说起。"),
    ]


def test_parse_tolerates_bom_and_crlf():
    entries = parse_srt("\ufeff" + _SAMPLE.replace("\n", "\r\n"))
    assert len(entries) == 3
    assert entries[2][2] == "首先从案例说起。"


def test_parse_rejects_unrecognizable_timeline():
    with pytest.raises(ValueError, match="时间轴"):
        parse_srt("这一块没有时间轴。")


def test_source_duration_is_the_last_end_time(tmp_path):
    assert _write(tmp_path).duration() == pytest.approx(12.0)


def test_source_window_alignment(tmp_path):
    head = _write(tmp_path).content(0, 5)
    assert "大家好" in head and "首先" not in head


def test_source_overlap_windows_share_the_boundary_subtitle(tmp_path):
    source = _write(tmp_path)
    head = source.content(2, 6)
    tail = source.content(4, 10)
    assert "媒体融合" in head and "媒体融合" in tail  # 跨窗字幕两边都拿得到


def test_source_returns_empty_beyond_duration(tmp_path):
    assert _write(tmp_path).content(100, 200) == ""


def test_source_is_deterministic(tmp_path):
    source = _write(tmp_path)
    assert source.content(0, source.duration()) == source.content(0, source.duration())


def test_source_satisfies_media_source_socket(tmp_path):
    assert isinstance(_write(tmp_path), MediaSource)


def test_source_rejects_empty_subtitle_file(tmp_path):
    path = tmp_path / "empty.srt"
    path.write_text("\n\n123\n", encoding="utf-8")
    with pytest.raises(ValueError, match="没有可用内容"):
        SrtSource(path)


def test_cli_demo_with_srt_runs_and_is_deterministic(tmp_path, capsys):
    path = tmp_path / "节目.srt"
    path.write_text(_SAMPLE, encoding="utf-8")
    argv = ["demo", "--srt", str(path), "--shard-seconds", "5", "--overlap-seconds", "1"]
    main(argv)
    first = capsys.readouterr().out
    main(argv)
    second = capsys.readouterr().out
    assert "字幕" in first
    assert first == second
