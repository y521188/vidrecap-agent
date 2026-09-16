"""修正执行：按计划调修正器、重打分、过护栏、不合格回退原句。

完整流程：

1. 用规划层的 `split_sentences` 把每段摘要拆成句子；
2. 逐句 await 打分器（规则层的标准；打分器是异步插座，慢实现自己在线程里跑）；
3. 向规划层要修正计划 `plan_corrections`；
4. 按计划调用修正器（外部层插座），对修正结果重新打分；
5. 用规则层的护栏检查忠实性——**没过护栏、或者分数没变好，一律回退原句**，
   宁可保留原样，也不接受"改出新事实"或"越改越糟"；
6. 重组摘要，记录平均质量分与修正条数，回填进 PartialSummary。

本层只执行、不发明策略：阈值与权重的默认值在数据层的 QualityConfig，
"该修哪几句"由规划层决定，"什么算越界"由规则层判定。
"""

from __future__ import annotations

from vidrecap.data.api import PartialSummary, QualityConfig, SentenceScore
from vidrecap.external.api import QualityScorer, SentenceCorrector
from vidrecap.planning.api import plan_corrections, split_sentences
from vidrecap.rules.api import check_faithfulness

# 分句之间用什么拼接：原文里没有分隔符时保持原样，有分隔符的重组后会被归一化
_JOINER = ""


def _average(total_scores: list[float]) -> float | None:
    if not total_scores:
        return None
    return sum(total_scores) / len(total_scores)


async def apply_corrections(
    partials: list[PartialSummary],
    context_by_shard: dict[int, str],
    scorer: QualityScorer,
    corrector: SentenceCorrector,
    config: QualityConfig | None = None,
) -> list[PartialSummary]:
    """对局部摘要做"按句打分 → 低分修正 → 重打分 → 护栏"的处理。

    context_by_shard 是分片序号到该片段原文的映射，既用于打分（判断句子
    是否缺失信息），也用于护栏（判断修正是否引入了原文没有的实体）。
    返回更新后的 partials（修正后的摘要、平均分、修正条数）。
    """
    cfg = config or QualityConfig()
    processed: list[PartialSummary] = []

    for partial in partials:
        context = context_by_shard.get(partial.shard_index, "")
        sentences = split_sentences(partial.summary)
        scores = [await scorer.score(sentence, context) for sentence in sentences]
        plan = plan_corrections(sentences, scores, cfg)

        final_sentences = list(sentences)
        final_scores = list(scores)
        corrected_count = 0

        for target in plan.targets:
            try:
                candidate = await corrector.correct(target.sentence, context)
            except Exception:  # 修正器出问题不该拖垮整条流水线：保留原句
                continue

            if check_faithfulness(candidate, context):
                continue  # 越过护栏：宁可保留原样，也不接受编造的内容

            rescored = await scorer.score(candidate, context)
            if rescored.total < target.score:
                continue  # 越改越糟：回退

            final_sentences[target.index] = candidate
            final_scores[target.index] = rescored
            if candidate != target.sentence:
                corrected_count += 1

        summary = (
            partial.summary if corrected_count == 0 else _JOINER.join(final_sentences)
        )
        processed.append(
            partial.model_copy(
                update={
                    "summary": summary,
                    "avg_quality": _average([score.total for score in final_scores]),
                    "corrected_count": corrected_count,
                }
            )
        )

    return processed
