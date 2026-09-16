"""端到端测试：注毒 → 质检回路 → 全链路验证。

四条产品级断言：

1. 注毒时修正真的发生（corrected_count > 0）；
2. 最终概括里没有原文之外的实体（无幻觉）；
3. 修正让平均分上升；
4. 同一输入跑两次，输出逐字节一致（确定性兜底）。

规划里曾打算把这些做成 monitor/evals/scenarios.py，实现时发现它们没有
生产调用方——纯粹是测试断言，按 YAGNI 直接放在本文件，不单设模块。
"""

import re

from vidrecap.data.api import PipelineConfig
from vidrecap.external.api import DemoCorrector, DemoLLM, DemoSource
from vidrecap.rules.api import HeuristicScorer, check_faithfulness
from vidrecap.service.api import run_recap

# demo 假模型截断尾部句子，不注毒也会有低分句，因此 poison 用 0.5 拉开差距
_POISON = 0.5


async def _run(poison_rate: float = 0.0, with_quality: bool = True, hours: float = 1.0):
    source = DemoSource(hours=hours, poison_rate=poison_rate)
    kwargs = (
        dict(scorer=HeuristicScorer(), corrector=DemoCorrector()) if with_quality else {}
    )
    return source, await run_recap(
        source, DemoLLM(), PipelineConfig(context_limit=1200), **kwargs
    )


async def test_poisoned_run_triggers_corrections_and_off_switch_disables_them():
    source, poisoned = await _run(_POISON)
    assert poisoned.stats.corrected_count > 0
    assert poisoned.stats.avg_quality is not None

    _, unpoisoned_off = await _run(with_quality=False)
    assert unpoisoned_off.stats.corrected_count == 0
    assert unpoisoned_off.stats.avg_quality is None


async def test_final_recap_contains_no_entities_outside_the_source():
    source, result = await _run(_POISON)
    body = re.sub(r"\[片段\d+\]", "", result.recap)  # 合并时的序号标签不算内容
    assert check_faithfulness(body, source.content(0, source.duration())) == []


async def test_corrections_raise_the_average_score():
    source_raw, raw = await _run(_POISON, with_quality=False)
    _, fixed = await _run(_POISON)

    scorer = HeuristicScorer()
    before = [
        (await scorer.score(p.summary, source_raw.content(0, source_raw.duration()))).total
        for p in raw.partials
    ]
    after = [p.avg_quality for p in fixed.partials if p.avg_quality is not None]

    assert len(before) == len(after) and before
    assert sum(after) / len(after) > sum(before) / len(before)


async def test_end_to_end_is_deterministic():
    def key(result):
        """elapsed_sec 是真实计时，两次运行必然不同，不参与比较。"""
        partials = [
            (p.shard_index, p.summary, p.avg_quality, p.corrected_count)
            for p in result.partials
        ]
        return result.recap, result.incremental_recap, result.stats, partials

    first = await _run(_POISON)
    second = await _run(_POISON)
    assert key(first[1]) == key(second[1])
