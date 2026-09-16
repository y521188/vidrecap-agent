"""后台内容目录测试：插座形状、取窗语义、人物档案统计、确定性与模型校验。"""

import pytest
from pydantic import ValidationError

from vidrecap.data.api import SpeakerProfile, SubtitleLine
from vidrecap.external.api import ContentCatalog, DemoCatalog


async def test_demo_catalog_satisfies_content_catalog_socket():
    assert isinstance(DemoCatalog(hours=0.5), ContentCatalog)


async def test_lines_window_semantics():
    catalog = DemoCatalog(hours=0.5)
    head = await catalog.lines(0, 16)
    assert [(line.start, line.end) for line in head] == [(0.0, 8.0), (8.0, 16.0)]
    assert await catalog.lines(10**6, 10**6 + 8) == []  # 超出内容时长
    # 跨窗行：与窗口只要有交集就算命中（重叠缓冲语义）
    straddle = await catalog.lines(8, 10)
    assert [line.start for line in straddle] == [8.0]


async def test_all_lines_are_well_formed():
    catalog = DemoCatalog(hours=0.2)
    lines = await catalog.lines(0, 10**9)
    assert lines
    for line in lines:
        assert line.speaker
        assert line.text.endswith("。")
        assert line.end > line.start


async def test_speaker_profiles_reflect_tier_and_frequency():
    catalog = DemoCatalog(hours=1.0)
    lines = await catalog.lines(0, 10**9)
    profiles = await catalog.speaker_profiles()
    assert set(profiles) == {line.speaker for line in lines}
    assert {p.tier for p in profiles.values()} == {"vip", "regular"}
    for profile in profiles.values():
        actual = sum(1 for line in lines if line.speaker == profile.name)
        assert profile.appearances == actual


async def test_vip_share_is_a_stable_minority():
    """大咖约占三成发言——人物权重策略考卷的稳定出题依据。"""
    catalog = DemoCatalog(hours=1.0)
    lines = await catalog.lines(0, 10**9)
    vips = {
        name
        for name, profile in (await catalog.speaker_profiles()).items()
        if profile.tier == "vip"
    }
    share = sum(1 for line in lines if line.speaker in vips) / len(lines)
    assert 0.2 < share < 0.4


async def test_two_instances_are_identical():
    a, b = DemoCatalog(hours=0.5), DemoCatalog(hours=0.5)
    assert await a.lines(0, 10**9) == await b.lines(0, 10**9)
    assert await a.speaker_profiles() == await b.speaker_profiles()


def test_speaker_profile_rejects_unknown_tier():
    with pytest.raises(ValidationError):
        SpeakerProfile(name="无名之辈", tier="boss")


def test_subtitle_line_defaults_allow_unknown_speaker():
    line = SubtitleLine(start=0, end=8, text="有人说了句话。")
    assert line.speaker == ""
