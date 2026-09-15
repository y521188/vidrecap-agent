"""考卷加载器：把 JSONL 变成用例对象。

格式约定：一行一条 JSON，UTF-8，**统一用 LF 换行**（Windows 上 clone 时
换行符会被转成 CRLF，所以读取时要容忍 \r\n）。待第 2 次提交实现。
"""

from __future__ import annotations

from pathlib import Path

from vidrecap.monitor.evals.schemas import CorrectorCase, ScorerCase

CASES_DIR = Path(__file__).resolve().parent / "cases"
SCORER_CASES_FILE = CASES_DIR / "scorer_v1.jsonl"
CORRECTOR_CASES_FILE = CASES_DIR / "corrector_v1.jsonl"


def load_scorer_cases(path: Path | None = None) -> list[ScorerCase]:
    """加载 A 层考卷（默认取内置 scorer_v1.jsonl）。"""
    raise NotImplementedError("待第 2 次提交实现：JSONL 考卷加载器")


def load_corrector_cases(path: Path | None = None) -> list[CorrectorCase]:
    """加载 B 层考卷（默认取内置 corrector_v1.jsonl）。"""
    raise NotImplementedError("待第 3 次提交实现：JSONL 考卷加载器")
