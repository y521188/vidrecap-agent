# -*- coding: utf-8 -*-
"""一次性测评脚本：打分器对英文是不是失明？英文句子有没有被放跑？"""
import asyncio
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

from vidrecap.planning.api import split_sentences
from vidrecap.rules.api import (
    HeuristicScorer,
    check_faithfulness,
    extract_entities,
    unacceptable_reason,
)

scorer = HeuristicScorer()


async def run_case(name: str, recap: str) -> None:
    sents = split_sentences(recap)
    print("=" * 70)
    print(f"【{name}】split_sentences 切出 {len(sents)} 句")
    totals = []
    for s in sents:
        sc = await scorer.score(s, "")
        reason = unacceptable_reason(sc)
        totals.append(sc.total)
        flag = "不合格" if reason else "达  标"
        preview = s.replace("\n", "⏎")
        preview = preview[:56] + "…" if len(preview) > 56 else preview
        print(f"  [{flag}] {sc.total:.3f} (清{sc.clarity:.2f} 通{sc.fluency:.2f} 完{sc.completeness:.2f}) {preview}")
        if reason:
            print(f"         └ 原因: {reason}")
    print(f"  → 平均分 {sum(totals) / len(totals):.3f}（历史记录值对照见上）")


async def main() -> None:
    with open(r"D:\ynt\视频分析\vidrecap-agent\.vidrecap\history.jsonl", encoding="utf-8") as f:
        hist = [json.loads(line) for line in f]

    # 实验一：历史任务里的真实产出
    await run_case(f"任务1 sintel demo 英文直出 (历史avg={hist[0]['stats']['avg_quality']}, 修正{hist[0]['stats']['corrected_count']}句)", hist[0]["recap"])
    await run_case(f"任务3 hello.wav 英文截断 (历史avg={hist[2]['stats']['avg_quality']}, 修正{hist[2]['stats']['corrected_count']}句)", hist[2]["recap"])
    await run_case(f"任务8 qwen-plus 真模型 (历史avg={hist[7]['stats']['avg_quality']}, 修正{hist[7]['stats']['corrected_count']}句)", hist[7]["recap"])

    # 实验二：定点雷区——每句单独喂给打分器（模拟"如果会切英文句号"的情形）
    print("=" * 70)
    print("【实验二】定点雷区（逐句打分，看打分器能不能区分烂英文和好英文）")
    mines = [
        "Bonnie failed her C.",              # tiny 转写的乱码句
        "Be the dragonlands in town.",       # 乱码句之二
        "You're a fool for traveling alone so completely unprepared.",  # 正常英文好句
        "the the the of and and and to a a a a.",  # 词重复的垃圾句
        "he said he said he said he said he said.",  # 指代堆积
        "介绍介绍了这个这个那个那个的问题。",  # 对照组：同烂程度的中文句
    ]
    for m in mines:
        sc = await scorer.score(m, "")
        reason = unacceptable_reason(sc)
        flag = "不合格" if reason else "达  标"
        print(f"  [{flag}] {sc.total:.3f} (清{sc.clarity:.2f} 通{sc.fluency:.2f} 完{sc.completeness:.2f}) {m}")
        if reason:
            print(f"         └ 原因: {reason}")
        else:
            print("         └ 原因: （无——放行）")

    # 实验三：护栏对英文幻觉设不设防
    print("=" * 70)
    print("【实验三】忠实性护栏——英文幻觉 vs 中文幻觉")
    context = "You're a fool for traveling alone so completely unprepared."
    en_halluc = "Sintel defeated the evil dragon and won 5000 gold coins in Dragonland."
    zh_halluc = "主角击败了邪恶巨龙，在龙境赢得五千金币。"
    print(f"  英文幻觉句实体抽取结果: {extract_entities(en_halluc)}")
    print(f"  护栏判定（英文，空列表=放行）: {check_faithfulness(en_halluc, context)}")
    print(f"  护栏判定（中文对照，非空=拦截）: {check_faithfulness(zh_halluc, '孤立无援的旅行者是傻瓜。')}")


asyncio.run(main())
