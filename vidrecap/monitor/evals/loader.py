"""考卷加载器：把 JSONL 变成用例对象。

格式约定：一行一条 JSON，UTF-8，**统一用 LF 换行**（Windows 上 clone 时
换行符会被转成 CRLF，所以读取按行切分、天然容忍 \r\n）。
空白行与以 # 开头的行会被跳过，方便在考卷里写分组说明。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from vidrecap.monitor.evals.schemas import CorrectorCase, ScorerCase

CASES_DIR = Path(__file__).resolve().parent / "cases"
SCORER_CASES_FILE = CASES_DIR / "scorer_v1.jsonl"
CORRECTOR_CASES_FILE = CASES_DIR / "corrector_v1.jsonl"

_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _load_jsonl(path: Path, model: type[_ModelT]) -> list[_ModelT]:
    """按行读 JSONL，逐条校验，出错时报出具体行号。"""
    if not path.exists():
        raise FileNotFoundError(f"考卷文件不存在：{path}")

    cases: list[_ModelT] = []
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            cases.append(model.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"{path.name} 第 {lineno} 行不是合法用例：{exc}") from exc

    if not cases:
        raise ValueError(f"{path.name} 里没有任何用例")

    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"{path.name} 里 id 重复：{case.id}")
        seen.add(case.id)

    return cases


def load_scorer_cases(path: Path | None = None) -> list[ScorerCase]:
    """加载 A 层考卷（默认取内置 scorer_v1.jsonl）。"""
    return _load_jsonl(path or SCORER_CASES_FILE, ScorerCase)


def load_corrector_cases(path: Path | None = None) -> list[CorrectorCase]:
    """加载 B 层考卷（默认取内置 corrector_v1.jsonl）。"""
    return _load_jsonl(path or CORRECTOR_CASES_FILE, CorrectorCase)
