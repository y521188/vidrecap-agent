"""任务登记簿的落盘形态（数据层）：一个任务一个 JSON 文件。

与 HistoryStore 的分工——都在"任务持久化"这条线上，但一个档案一个号牌：

- HistoryStore 是**档案**：跑过什么，只追加、供回看；
- JobStore 是**取餐牌**：凭任务号查进度、取结果，可更新。

重启自愈口径：服务重启后已完成的任务仍可凭号取结果；没跑完的标成
"interrupted"，提示重新提交——转写缓存与分片缓存都在，重跑很快。
"""

from __future__ import annotations

import json
from pathlib import Path


class JobStore:
    """任务号牌簿：``<目录>/<job_id>.json`` 一任务一文件，原子写。"""

    def __init__(self, path: str | Path) -> None:
        self._dir = Path(path)

    def save(self, job_id: str, snapshot: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        dest = self._dir / f"{job_id}.json"
        partial = dest.with_suffix(".json.part")
        partial.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        partial.replace(dest)

    def get(self, job_id: str) -> dict | None:
        dest = self._dir / f"{job_id}.json"
        if not dest.exists():
            return None
        try:
            return json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # 半截/损坏的号牌当不存在：宁可 404 也不回脏数据

    def mark_interrupted(self) -> int:
        """服务重启的收尾：上个进程留下的 running 任务标成 interrupted。"""
        count = 0
        if not self._dir.exists():
            return count
        for dest in self._dir.glob("*.json"):
            try:
                snapshot = json.loads(dest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if snapshot.get("status") == "running":
                snapshot["status"] = "interrupted"
                snapshot["error"] = (
                    "服务重启导致任务中断，请重新提交（转写与分片缓存仍在，重跑很快）"
                )
                dest.write_text(
                    json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
                )
                count += 1
        return count
