"""技能文件测试：受限头部解析、错误提示、优先级（命令行 > 技能 > 默认）、双级提示词布线。"""

import pytest

from vidrecap.data.api import PipelineConfig
from vidrecap.external.api import DemoSource
from vidrecap.service.api import run_recap
from vidrecap.user.api import build_parser, load_skill
from vidrecap.user.cli import _build_config, _build_quality
from vidrecap.user.api import main

_SKILL = """---
name: 新闻摘要
description: 面向新闻类长视频
system_prompt:
  你是资深新闻编辑。
  只依据给定内容写作。
threshold: 0.75
weights: 0.6, 0.2, 0.2
min_share: 0.1
---

提炼每段的论点与结论。
"""


def _write(tmp_path, text: str = _SKILL):
    path = tmp_path / "skill.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_skill_reads_header_and_body(tmp_path):
    skill = load_skill(_write(tmp_path))
    assert skill.name == "新闻摘要"
    assert skill.system_prompt == "你是资深新闻编辑。\n只依据给定内容写作。"
    assert skill.summarize_instruction == "提炼每段的论点与结论。"
    assert skill.threshold == 0.75
    assert skill.weights == [0.6, 0.2, 0.2]
    assert skill.min_share == 0.1


def test_metadata_only_skill_keeps_everything_empty(tmp_path):
    skill = load_skill(_write(tmp_path, "---\nname: 只有元数据\n---\n"))
    assert skill.summarize_instruction == ""
    assert skill.threshold is None
    assert skill.weights is None


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("没有头部", "必须以 --- 头部开始"),
        ("---\nname: x\n", "没有收尾"),
        ("---\n不是键值对\n---\n", "不是 key: value"),
        ("---\nweights: 0.5, 0.3\n---\n", "weights"),
        ("---\nthreshold: 挺高\n---\n", "threshold"),
        ("---\n  孤零零的缩进\n---\n", "没有归属"),
    ],
)
def test_bad_skill_files_report_clearly(tmp_path, text, match):
    with pytest.raises(ValueError, match=match):
        load_skill(_write(tmp_path, text))


def test_command_line_beats_skill_file(tmp_path):
    skill = load_skill(_write(tmp_path))
    args = build_parser().parse_args(
        ["demo", "--threshold", "0.9", "--weights", "1", "0", "0", "--instruction", "命令行指令"]
    )
    config = _build_config(args, skill)
    _, _, quality = _build_quality(args, skill)
    assert config.summarize_instruction == "命令行指令"
    assert config.system_prompt == skill.system_prompt  # 技能提供的系统提示词照旧生效
    assert quality.threshold == 0.9
    assert quality.clarity_weight == 1.0


def test_skill_file_beats_defaults(tmp_path):
    skill = load_skill(_write(tmp_path))
    args = build_parser().parse_args(["demo"])
    config = _build_config(args, skill)
    _, _, quality = _build_quality(args, skill)
    assert config.summarize_instruction == "提炼每段的论点与结论。"
    assert quality.threshold == 0.75
    assert quality.clarity_weight == 0.6


def test_without_skill_nothing_changes():
    args = build_parser().parse_args(["demo"])
    config = _build_config(args, None)
    assert config.summarize_instruction == PipelineConfig().summarize_instruction
    assert config.system_prompt == ""


class _RecordingLLM:
    """记录每次调用的两级提示词，用来验证双重约束确实传到了模型。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def summarize(self, text: str, instruction: str = "", system: str = "") -> str:
        self.calls.append((text, instruction, system))
        return "摘要。"


async def test_both_prompts_reach_the_model():
    llm = _RecordingLLM()
    config = PipelineConfig(
        shard_seconds=600,
        overlap_seconds=30,
        context_limit=1200,
        summarize_instruction="提炼论点",
        system_prompt="你是资深编辑。",
    )
    await run_recap(DemoSource(hours=0.2), llm, config)
    assert llm.calls
    for _text, instruction, system in llm.calls:
        assert instruction == "提炼论点"
        assert system == "你是资深编辑。"


def test_cli_demo_with_skill_runs(tmp_path, capsys):
    main(["demo", "--skill", str(_write(tmp_path)), "--hours", "0.2", "--no-correct"])
    out = capsys.readouterr().out
    assert "技能 新闻摘要" in out
    assert "模拟视频" in out
