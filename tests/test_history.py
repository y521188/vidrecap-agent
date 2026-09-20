"""历史档案（HistoryStore / RunRecord）测试：追加、回看、坏行报错。"""

import pytest

from vidrecap.data.api import HistoryStore, RecapStats, RunRecord


def _record(record_id: str, created_at: float, recap: str = "概括") -> RunRecord:
    return RunRecord(
        id=record_id,
        created_at=created_at,
        recap=recap,
        stats=RecapStats(
            duration_sec=60.0,
            shard_count=1,
            shard_seconds=600.0,
            overlap_seconds=30.0,
            partial_count=1,
            incremental_at=0.8,
        ),
    )


def test_append_then_latest_is_newest_first(tmp_path):
    store = HistoryStore(tmp_path / "history.jsonl")
    store.append(_record("a", 1.0))
    store.append(_record("b", 2.0))
    assert [record.id for record in store.latest()] == ["b", "a"]


def test_latest_respects_limit_and_get_roundtrips(tmp_path):
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    for index in range(5):
        store.append(_record(f"id{index}", float(index), recap=f"第{index}次"))
    assert [record.id for record in store.latest(limit=3)] == ["id4", "id3", "id2"]
    got = store.get("id2")
    assert got is not None
    assert got.recap == "第2次"
    assert got.stats.duration_sec == 60.0
    assert store.get("不存在") is None


def test_missing_file_reads_as_empty(tmp_path):
    assert HistoryStore(tmp_path / "不存在.jsonl").latest() == []


def test_corrupt_line_raises_instead_of_skipping(tmp_path):
    """档案被悄悄跳行比报错更糟：认不出的行必须带着行号浮出来。"""
    path = tmp_path / "history.jsonl"
    store = HistoryStore(path)
    store.append(_record("a", 1.0))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("不是 JSON 的一行\n")
    with pytest.raises(ValueError, match="第 2 行"):
        HistoryStore(path).latest()


def test_records_survive_process_restart(tmp_path):
    """档案的意义就在跨进程：换一个 store 实例还能读到旧记录。"""
    path = tmp_path / "history.jsonl"
    HistoryStore(path).append(_record("a", 1.0, recap="上次的成果"))
    reloaded = HistoryStore(path).get("a")
    assert reloaded is not None
    assert reloaded.recap == "上次的成果"
