"""时序分片：均等切分 + 边缘重叠缓冲区。

固定切片的问题：一句话、一个剧情节点正好落在切点上会被拦腰斩断，
上下文割裂后局部摘要质量骤降。这里每个分片的责任区仍是均等的，
但取材时向前后各扩 overlap 秒作为缓冲区，保证切点附近的语义完整。
"""

from __future__ import annotations

from .models import Shard
from .protocols import MediaSource


def plan_windows(
    duration: float, shard_seconds: float, overlap_seconds: float
) -> list[tuple[float, float]]:
    """切出带重叠缓冲区的时间窗列表 [(buffered_start, buffered_end), ...]。

    责任区首尾贴边截断；overlap 必须小于单分片时长，否则分片失去意义。
    """
    if duration <= 0:
        raise ValueError("duration must be positive")
    if shard_seconds <= 0:
        raise ValueError("shard_seconds must be positive")
    if overlap_seconds < 0:
        raise ValueError("overlap_seconds cannot be negative")
    if overlap_seconds >= shard_seconds:
        raise ValueError("overlap_seconds must be smaller than shard_seconds")

    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < duration - 1e-9:
        core_end = min(start + shard_seconds, duration)
        buffered_start = max(0.0, start - overlap_seconds)
        buffered_end = min(duration, core_end + overlap_seconds)
        windows.append((buffered_start, buffered_end))
        start = core_end
    return windows


def shard(
    source: MediaSource, shard_seconds: float, overlap_seconds: float
) -> list[Shard]:
    """按时间窗切分媒体内容，产出带缓冲区文本的分片列表。"""
    duration = source.duration()
    shards: list[Shard] = []
    for i, (buf_start, buf_end) in enumerate(
        plan_windows(duration, shard_seconds, overlap_seconds)
    ):
        shards.append(
            Shard(
                index=i,
                core_start=i * shard_seconds,
                core_end=min((i + 1) * shard_seconds, duration),
                buffered_start=buf_start,
                buffered_end=buf_end,
                text=source.content(buf_start, buf_end),
            )
        )
    return shards
