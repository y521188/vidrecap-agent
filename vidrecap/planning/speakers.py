"""人物权重策略：大咖与高频人物优先保留，低频配角过滤。

纯判断：给字幕行与人物档案，产出"留哪些、删哪些"的计划（纯数据），
服务层照计划执行。三条规则，按顺序判：

1. 源里没有人物档案（无标签源）→ 全保留，策略不误伤；
2. 说话人是大咖（vip）或档案缺失/匿名（空串）→ 保留；
3. 常规人物的台词占比低于阈值 → 过滤。

阈值默认值在数据层 SpeakerPolicyConfig，本模块不出现数字。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from vidrecap.data.api import SpeakerPlan, SpeakerPolicyConfig, SpeakerProfile, SubtitleLine


def plan_speaker_policy(
    lines: Sequence[SubtitleLine],
    profiles: Mapping[str, SpeakerProfile],
    config: SpeakerPolicyConfig | None = None,
) -> SpeakerPlan:
    """按人物权重出取舍计划；占比分母是传入的全部行数。"""
    config = config or SpeakerPolicyConfig()
    if not profiles:  # 无标签源：策略整体不参与
        return SpeakerPlan(keep=list(lines))

    counts = Counter(line.speaker for line in lines)
    total = len(lines)
    keep: list[SubtitleLine] = []
    drop: list[SubtitleLine] = []
    for line in lines:
        profile = profiles.get(line.speaker)
        if profile is None or profile.tier == "vip" or counts[line.speaker] / total >= config.min_share:
            keep.append(line)
        else:
            drop.append(line)
    return SpeakerPlan(keep=keep, drop=drop, dropped_speakers=sorted({line.speaker for line in drop}))
