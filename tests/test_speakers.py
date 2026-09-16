"""人物权重策略测试：计划纯函数 + 流水线接入（大咖保留、配角过滤、无标签源不误伤）。"""

from vidrecap.data.api import (
    PipelineConfig,
    SpeakerPolicyConfig,
    SpeakerProfile,
    SubtitleLine,
)
from vidrecap.external.api import DemoCatalog, DemoLLM, DemoSource
from vidrecap.planning.api import plan_speaker_policy
from vidrecap.service.api import Orchestrator, shard
from vidrecap.user.api import main


def _many(speaker: str, n: int, offset: int = 0) -> list[SubtitleLine]:
    return [
        SubtitleLine(
            start=(offset + i) * 8.0, end=(offset + i + 1) * 8.0, text=f"句{offset + i}。", speaker=speaker
        )
        for i in range(n)
    ]


def test_no_profiles_keeps_everything():
    """无人物标签的源：策略整体不参与，一句不删。"""
    lines = _many("甲", 3) + [SubtitleLine(start=24.0, end=32.0, text="匿名。", speaker="")]
    plan = plan_speaker_policy(lines, {})
    assert plan.keep == lines and plan.drop == []


def test_anonymous_and_vip_lines_always_kept():
    lines = _many("", 2) + _many("大咖", 1, offset=2)
    profiles = {"大咖": SpeakerProfile(name="大咖", tier="vip", appearances=1)}
    plan = plan_speaker_policy(lines, profiles)
    assert plan.keep == lines and plan.drop == []


def test_regular_below_min_share_dropped_boundary_kept():
    profiles = {
        "常驻": SpeakerProfile(name="常驻", appearances=99),
        "配角": SpeakerProfile(name="配角", appearances=1),
    }
    lines = _many("常驻", 99) + _many("配角", 1, offset=99)  # 配角占比 1% < 5%
    plan = plan_speaker_policy(lines, profiles)
    assert [line.speaker for line in plan.drop] == ["配角"]
    assert plan.dropped_speakers == ["配角"]
    assert all(line.speaker == "常驻" for line in plan.keep)

    boundary = _many("常驻", 95) + _many("配角", 5, offset=95)  # 恰好 5% → 保留（>=）
    assert plan_speaker_policy(boundary, profiles).drop == []


def test_custom_threshold_is_honored():
    lines = _many("甲", 7) + _many("乙", 3, offset=7)
    profiles = {
        "甲": SpeakerProfile(name="甲", appearances=7),
        "乙": SpeakerProfile(name="乙", appearances=3),
    }
    plan = plan_speaker_policy(lines, profiles, SpeakerPolicyConfig(min_share=0.4))
    assert plan.dropped_speakers == ["乙"]


def test_shard_assembles_from_kept_lines_with_overlap():
    source = DemoSource(hours=0.5)
    lines = [
        SubtitleLine(start=0.0, end=8.0, text="第一句。", speaker="甲"),
        SubtitleLine(start=596.0, end=604.0, text="跨界句。", speaker="甲"),
        SubtitleLine(start=632.0, end=640.0, text="二窗句。", speaker="甲"),
    ]
    shards = shard(source, 600, 30, lines=lines)
    assert shards[0].text == "第一句。\n跨界句。"  # 跨界句落在重叠缓冲区，两窗都拿得到
    assert shards[1].text == "跨界句。\n二窗句。"


async def test_orchestrator_filters_extras_from_catalog():
    catalog = DemoCatalog(hours=0.5)
    config = PipelineConfig(shard_seconds=600, overlap_seconds=30, context_limit=1200)
    result = await Orchestrator(
        DemoLLM(), config=config, catalog=catalog
    ).run(DemoSource(hours=0.5))

    assert result.stats.dropped_speakers == ["群众演员"]
    assert result.stats.dropped_lines == 1
    body = result.recap + "".join(p.summary for p in result.partials)
    assert "群众演员" not in body, "被过滤的配角不得进任何摘要"
    assert ("张教授" in body) or ("李首席" in body), "大咖发言必须保留"


def test_cli_catalog_demo_reports_filtering(capsys):
    main(["demo", "--catalog", "--hours", "0.5", "--no-correct"])
    out = capsys.readouterr().out
    assert "目录取数" in out
    assert "过滤配角 群众演员（1 句）" in out
