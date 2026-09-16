"""假后台目录：内存 sqlite 预置大咖与配角，离线演示"取字幕 + 人物标签"。

模拟客户后台的真实形态（数据库）——查询全部参数绑定（``?`` 占位符），
这是硬约束，不是风格偏好。真实适配器对接 HTTP/远程库时，请把阻塞调用
用 asyncio.to_thread 包起来（与 QualityScorer 的口径一致）。

人物出场按句子序号确定性轮换：大咖约占三成发言，配角分剩下的；
appearances 由生成结果统计而来——人物权重策略的考卷由此有了稳定出题人。
"""

from __future__ import annotations

import random
import sqlite3

from vidrecap.data.api import SpeakerProfile, SubtitleLine

LINE_SECONDS = 8.0
_VIP_SHARE = 0.3

_VIP = ["张教授", "李首席"]
_REGULAR = ["记者小王", "现场观众甲", "特约评论员"]
_VERBS = ["分析了", "介绍了", "解读了", "回顾了"]
_TOPICS = ["媒体融合趋势", "平台推荐算法", "内容审核标准", "短视频生态"]

_TAIL = "，并结合现场案例给出了详细说明。"


class DemoCatalog:
    """离线假后台：内存 sqlite，两张表（字幕行、人物档案），确定性种子。"""

    def __init__(self, hours: float = 3.0) -> None:
        if hours <= 0:
            raise ValueError("hours must be positive")
        self._duration = hours * 3600.0
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute(
            "CREATE TABLE subtitle_lines (start_seconds REAL NOT NULL, end_seconds REAL NOT NULL, text TEXT NOT NULL, speaker TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE TABLE speakers (name TEXT NOT NULL PRIMARY KEY, tier TEXT NOT NULL, appearances INTEGER NOT NULL)"
        )
        self._seed_lines()
        self._seed_speakers()

    async def lines(self, start: float, end: float) -> list[SubtitleLine]:
        rows = self._conn.execute(
            "SELECT start_seconds, end_seconds, text, speaker FROM subtitle_lines WHERE start_seconds < ? AND end_seconds > ? ORDER BY start_seconds",
            # 占位符顺序：行开头 < 窗口结束，行结尾 > 窗口开始
            (end, start),
        ).fetchall()
        return [
            SubtitleLine(start=a, end=b, text=text, speaker=speaker)
            for a, b, text, speaker in rows
        ]

    async def speaker_profiles(self) -> dict[str, SpeakerProfile]:
        rows = self._conn.execute(
            "SELECT name, tier, appearances FROM speakers ORDER BY appearances DESC, name"
        ).fetchall()
        return {
            name: SpeakerProfile(name=name, tier=tier, appearances=count)
            for name, tier, count in rows
        }

    def close(self) -> None:
        self._conn.close()

    # --- 以下是确定性布种 ---

    def _seed_lines(self) -> None:
        total = int(self._duration // LINE_SECONDS)
        rows = []
        for i in range(total):
            # 固定位置埋一个只出现一次的群众演员——配角过滤效果的信标
            speaker = "群众演员" if i == 17 else self._speaker_for(i)
            rng = random.Random((i * 40503) % (2**32))
            text = f"{speaker}{rng.choice(_VERBS)}{rng.choice(_TOPICS)}{_TAIL}"
            rows.append((i * LINE_SECONDS, (i + 1) * LINE_SECONDS, text, speaker))
        self._conn.executemany(
            "INSERT INTO subtitle_lines (start_seconds, end_seconds, text, speaker) VALUES (?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    @staticmethod
    def _speaker_for(i: int) -> str:
        rng = random.Random((i * 2654435761) % (2**32))
        if rng.random() < _VIP_SHARE:
            return _VIP[i % len(_VIP)]
        return _REGULAR[i % len(_REGULAR)]

    def _seed_speakers(self) -> None:
        rows = [
            (name, "vip" if name in _VIP else "regular", count)
            for name, count in self._conn.execute(
                "SELECT speaker, COUNT(*) FROM subtitle_lines GROUP BY speaker"
            )
        ]
        self._conn.executemany(
            "INSERT INTO speakers (name, tier, appearances) VALUES (?, ?, ?)", rows
        )
        self._conn.commit()
