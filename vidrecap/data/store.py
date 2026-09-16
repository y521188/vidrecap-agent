"""任务持久化（断点续跑）：把分片摘要落进 sqlite，中途挂了接着跑。

缓存是**内容寻址**的：键 = 命名空间 + 分片原文的哈希。原文改一个字、
换个提示词或换个模型（namespace 不同），旧结果自动作废整片重算——
复用的前提是"算的东西一模一样"。

标准库 sqlite3，不加任何新依赖；不启用（不传 store）时零开销、行为不变。
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from vidrecap.data.models import PartialSummary


class TaskStore:
    """分片结果缓存：namespace 用来隔离"换了模型/提示词"的场景。

    全部查询都是常量 SQL + 参数化占位符（``?``），没有任何字符串拼装。
    """

    def __init__(self, path: str | Path, namespace: str = "") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS shard_cache (key TEXT NOT NULL, shard_index INTEGER NOT NULL, summary TEXT NOT NULL, avg_quality REAL, corrected_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (key, shard_index))"
        )
        self._conn.commit()
        self._seed = hashlib.sha256(f"{namespace}\x00".encode("utf-8")).digest()

    def key(self, text: str) -> str:
        """分片文本的缓存键：内容寻址，命名空间参与哈希。"""
        return hashlib.sha256(self._seed + text.encode("utf-8")).hexdigest()

    def load(self, key: str, shard_index: int) -> PartialSummary | None:
        row = self._conn.execute(
            "SELECT summary, avg_quality, corrected_count FROM shard_cache WHERE key = ? AND shard_index = ?",
            (key, shard_index),
        ).fetchone()
        if row is None:
            return None
        summary, avg_quality, corrected_count = row
        return PartialSummary(
            shard_index=shard_index,
            summary=summary,
            avg_quality=avg_quality,
            corrected_count=corrected_count,
        )

    def save(self, key: str, partial: PartialSummary) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO shard_cache (key, shard_index, summary, avg_quality, corrected_count) VALUES (?, ?, ?, ?, ?)",
            (
                key,
                partial.shard_index,
                partial.summary,
                partial.avg_quality,
                partial.corrected_count,
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TaskStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
