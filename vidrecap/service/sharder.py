"""分片执行：按规划层给的时间窗去媒体源取文本，组装成分片。

"窗怎么切"是规划层的事（plan_windows），"按窗取材"是本层的执行动作。
"""

from __future__ import annotations

from vidrecap.data.api import Shard
from vidrecap.external.api import MediaSource
from vidrecap.planning.api import plan_windows


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
