"""分片执行：按规划层给的时间窗取内容，组装成分片。

"窗怎么切"是规划层的事（plan_windows），"按窗取材"是本层的执行动作。
人物策略（plan_speaker_policy）产出的保留清单传进来时，取材只从
保留清单里拿——过滤是规划层定的，本层照做，不二次判断。
"""

from __future__ import annotations

from vidrecap.data.api import Shard, SubtitleLine
from vidrecap.external.api import MediaSource
from vidrecap.planning.api import plan_windows


def shard(
    source: MediaSource,
    shard_seconds: float,
    overlap_seconds: float,
    lines: list[SubtitleLine] | None = None,
) -> list[Shard]:
    """按时间窗切分内容。给了 lines 就按行组装（人物策略后的保留清单），否则读媒体源。"""
    duration = source.duration()
    shards: list[Shard] = []
    for i, (buf_start, buf_end) in enumerate(
        plan_windows(duration, shard_seconds, overlap_seconds)
    ):
        if lines is None:
            text = source.content(buf_start, buf_end)
        else:
            text = "\n".join(
                line.text
                for line in lines
                if line.start < buf_end and line.end > buf_start
            )
        shards.append(
            Shard(
                index=i,
                core_start=i * shard_seconds,
                core_end=min((i + 1) * shard_seconds, duration),
                buffered_start=buf_start,
                buffered_end=buf_end,
                text=text,
            )
        )
    return shards
