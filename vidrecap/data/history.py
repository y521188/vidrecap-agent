"""历史记录（任务档案）：把每次**跑成功**的请求参数与产出追加进 JSONL，供操作台回看。

与 TaskStore 的分工——同属"任务持久化"，但一个缓存一个档案：

- TaskStore 是**缓存**：内容寻址、可作废重算，只为断点续跑省模型调用；
- HistoryStore 是**档案**：只追加、永不改写、不参与任何计算，只为"回看当时跑了什么"。

口径：

- 只记成功的任务——失败那次在响应流里已经用 error 事件说清了，档案里只留成果；
- 服务是多线程的，读写共用一把锁；本地工具规模全量读文件再截取，不做索引；
- 文件里出现认不出的行直接报错：档案被悄悄跳行比列表打不开更糟。
"""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel

from vidrecap.data.models import RecapStats


class RunRecord(BaseModel):
    """一次成功运行的档案：当时怎么跑的（参数）+ 跑出了什么（概括与统计）。"""

    id: str
    created_at: float  # Unix 秒
    llm: str = "demo"
    model: str = ""
    source_name: str = ""  # 字幕文件名；内联文本或内置示例为空
    hours: float = 3.0
    instruction: str = ""
    catalog: bool = False
    no_correct: bool = False
    visual: bool = False
    diarize: bool = False
    recap: str
    stats: RecapStats


class HistoryStore:
    """JSONL 追加式档案：一行一条 RunRecord。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def append(self, record: RunRecord) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(record.model_dump_json() + "\n")

    def latest(self, limit: int = 50) -> list[RunRecord]:
        """最新的在前，最多 limit 条。"""
        return list(reversed(self._all()))[:limit]

    def get(self, record_id: str) -> RunRecord | None:
        for record in self._all():
            if record.id == record_id:
                return record
        return None

    def _all(self) -> list[RunRecord]:
        if not self._path.exists():
            return []
        with self._lock:
            text = self._path.read_text(encoding="utf-8")
        records: list[RunRecord] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(RunRecord.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"历史档案第 {number} 行无法解析: {exc}") from exc
        return records
