"""技能文件（skill-md）解析：格式对齐 Agent Skills 开放标准。

只认受限的平铺格式，**不引 YAML 库**（加依赖先问）：

    ---
    name: 新闻摘要
    description: 一句话说明
    system_prompt:
      缩进的行会并入上一个键（多行文本这样写）
    threshold: 0.75
    weights: 0.5, 0.3, 0.2
    min_share: 0.05
    ---
    正文（Markdown 原样）= 摘要指令

标准里正文就是技能指令，这里沿用：正文作为 summarize_instruction 的默认值，
头部写了 instruction 键则以它为准。本模块只负责"读出技能文件写了什么"，
命令行与技能文件的优先级合并由同层的 cli 装配根决定。
"""

from __future__ import annotations

from pathlib import Path

from vidrecap.data.api import SkillConfig

_WEIGHT_COUNT = 3


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """拆出头部键值与正文；缩进行并入上一键，空行忽略。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("技能文件必须以 --- 头部开始")
    body_start = next(
        (i + 1 for i in range(1, len(lines)) if lines[i].strip() == "---"), None
    )
    if body_start is None:
        raise ValueError("技能文件的头部没有收尾的 ---")

    fields: dict[str, str] = {}
    current: str | None = None
    for raw in lines[1 : body_start - 1]:
        if not raw.strip():
            continue
        if raw[:1].isspace():
            if current is None:
                raise ValueError(f"头部缩进行没有归属的键: {raw!r}")
            fields[current] = (
                f"{fields[current]}\n{raw.strip()}" if fields[current] else raw.strip()
            )
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            raise ValueError(f"头部行不是 key: value 形式: {raw!r}")
        current = key.strip()
        fields[current] = value.strip()
    return fields, "\n".join(lines[body_start:]).strip()


def _optional_float(fields: dict[str, str], key: str) -> float | None:
    if key not in fields:
        return None
    try:
        return float(fields[key])
    except ValueError as exc:
        raise ValueError(f"技能文件的 {key} 不是数字: {fields[key]!r}") from exc


def _optional_weights(fields: dict[str, str]) -> list[float] | None:
    if "weights" not in fields:
        return None
    parts = [piece.strip() for piece in fields["weights"].split(",")]
    if len(parts) != _WEIGHT_COUNT:
        raise ValueError("技能文件的 weights 要写三项、逗号分隔，如 0.5, 0.3, 0.2")
    try:
        return [float(piece) for piece in parts]
    except ValueError as exc:
        raise ValueError(f"技能文件的 weights 含非数字: {fields['weights']!r}") from exc


def load_skill(path: str | Path) -> SkillConfig:
    """读技能文件：头部给策略参数，正文给摘要指令。"""
    fields, body = _parse_frontmatter(Path(path).read_text(encoding="utf-8-sig"))
    return SkillConfig(
        name=fields.get("name", ""),
        description=fields.get("description", ""),
        system_prompt=fields.get("system_prompt", ""),
        summarize_instruction=fields.get("instruction", "") or body,
        threshold=_optional_float(fields, "threshold"),
        weights=_optional_weights(fields),
        min_share=_optional_float(fields, "min_share"),
    )
