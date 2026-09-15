"""时序分片测试：覆盖完整性、连续性、重叠缓冲区、参数校验。"""

import pytest

from vidrecap.core.sharder import plan_windows, shard


class FakeSource:
    def __init__(self, duration: float) -> None:
        self._duration = duration

    def duration(self) -> float:
        return self._duration

    def content(self, start: float, end: float) -> str:
        return f"{start:.0f}-{end:.0f}"


def test_windows_cover_whole_timeline():
    windows = plan_windows(duration=3600, shard_seconds=600, overlap_seconds=30)
    assert len(windows) == 6
    assert windows[0][0] == 0.0
    assert windows[-1][1] == 3600.0


def test_core_regions_are_contiguous():
    shards = shard(FakeSource(3600), shard_seconds=600, overlap_seconds=30)
    for prev, cur in zip(shards, shards[1:]):
        assert cur.core_start == prev.core_end


def test_internal_shards_have_overlap_buffer():
    shards = shard(FakeSource(3600), shard_seconds=600, overlap_seconds=30)
    for s in shards[1:]:
        assert s.buffered_start == pytest.approx(s.core_start - 30)
    for s in shards[:-1]:
        assert s.buffered_end == pytest.approx(s.core_end + 30)


def test_non_divisible_duration_keeps_tail_shard():
    shards = shard(FakeSource(3700), shard_seconds=600, overlap_seconds=30)
    assert shards[-1].core_end == 3700
    assert shards[-1].buffered_end == 3700


def test_text_covers_buffered_window():
    shards = shard(FakeSource(3600), shard_seconds=600, overlap_seconds=30)
    assert shards[1].text == f"{shards[1].buffered_start:.0f}-{shards[1].buffered_end:.0f}"


@pytest.mark.parametrize(
    "duration, shard_seconds, overlap",
    [(0, 600, 30), (-1, 600, 30), (3600, 0, 30), (3600, 600, -1), (3600, 600, 600)],
)
def test_invalid_params_raise(duration, shard_seconds, overlap):
    with pytest.raises(ValueError):
        plan_windows(duration, shard_seconds, overlap)
