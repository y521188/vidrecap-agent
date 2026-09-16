"""命令行实现。

零依赖体验：python -m vidrecap demo
（使用内置离线假数据，不需要任何 API Key）

两个命令：
- ``demo`` 用假数据跑通全流程；
- ``eval`` 跑评测集出成绩单，低于基线时以非零码退出（可以直接当门禁用）。

本文件是"装配根"：具体用哪个适配器、参数怎么给，只在这里组装一次；
命令行只做参数覆盖，不重复声明默认值（默认值在数据层的两个 Config）。
对外入口由 user/api 窗口挂出。
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from vidrecap.data.api import PipelineConfig, QualityConfig
from vidrecap.external.api import DemoCorrector, DemoLLM, DemoSource
from vidrecap.monitor.api import EvalReport, baseline_checks, run_eval
from vidrecap.rules.api import HeuristicScorer
from vidrecap.service.api import ProgressCallback, run_recap


def _bar(done: int, total: int, width: int = 28) -> str:
    filled = int(width * done / max(total, 1))
    return "[" + ">" * filled + "." * (width - filled) + f"] {done}/{total} 片段"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vidrecap", description="分治式长视频概括引擎"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="用内置离线假数据跑通全流程（质检修正默认开启）")
    demo.add_argument("--hours", type=float, default=3.0, help="模拟视频时长（小时）")
    demo.add_argument(
        "--shard-seconds", type=float, default=600.0, help="分片时长（秒）"
    )
    demo.add_argument(
        "--overlap-seconds", type=float, default=30.0, help="重叠缓冲区（秒）"
    )
    demo.add_argument("--concurrency", type=int, default=4, help="并行度")
    demo.add_argument(
        "--context-limit", type=int, default=1200, help="上下文字符上限，超限触发二分递归压缩"
    )
    demo.add_argument(
        "--poison",
        nargs="?",
        const=0.1,
        default=0.0,
        type=float,
        metavar="RATE",
        help="按比例确定性注入病句（默认 --poison 即 0.1），验证质检回路",
    )
    demo.add_argument(
        "--no-correct", action="store_true", help="关闭质检修正（打分、修正都不跑）"
    )
    demo.add_argument(
        "--threshold", type=float, default=None, help="覆盖判定阈值（默认 0.7）"
    )
    demo.add_argument(
        "--weights",
        nargs=3,
        type=float,
        default=None,
        metavar=("CLARITY", "FLUENCY", "COMPLETE"),
        help="覆盖三指标权重（需加和为 1，默认 0.5 0.3 0.2）",
    )

    evaluate = sub.add_parser("eval", help="跑评测集，打印成绩单（低于基线则退出码非零）")
    evaluate.add_argument(
        "--suite",
        choices=["scorer", "corrector", "all"],
        default="scorer",
        help="跑哪套考卷（corrector 待第 3 次提交实现）",
    )
    evaluate.add_argument(
        "--threshold", type=float, default=None, help="覆盖判定阈值（默认 0.7）"
    )
    return parser


def _build_config(args: argparse.Namespace) -> PipelineConfig:
    """把命令行参数覆盖到配置上（未给的字段沿用配置里的默认值）。"""
    return PipelineConfig(
        shard_seconds=args.shard_seconds,
        overlap_seconds=args.overlap_seconds,
        max_concurrency=args.concurrency,
        context_limit=args.context_limit,
    )


def _build_quality(args: argparse.Namespace):
    """装配质检回路：打分器、修正器与它们的配置；--no-correct 时全部为 None。"""
    if args.no_correct:
        return None, None, None

    overrides = {}
    if args.threshold is not None:
        overrides["threshold"] = args.threshold
    if args.weights is not None:
        overrides.update(
            clarity_weight=args.weights[0],
            fluency_weight=args.weights[1],
            completeness_weight=args.weights[2],
        )
    config = QualityConfig(**overrides) if overrides else None
    return HeuristicScorer(config), DemoCorrector(), config


async def run_demo(args: argparse.Namespace) -> None:
    scorer, corrector, quality_config = _build_quality(args)
    poison_note = f" | 注毒 {args.poison:.0%}" if args.poison else ""
    quality_note = "" if args.no_correct else " | 质检修正开"
    print(
        f"模拟视频 {args.hours} 小时 | 分片 {args.shard_seconds:.0f}s | "
        f"重叠缓冲 {args.overlap_seconds:.0f}s | 并行 {args.concurrency} | "
        f"上下文上限 {args.context_limit} 字符{poison_note}{quality_note}"
    )
    on_progress: ProgressCallback = lambda done, total: print(  # noqa: E731
        f"\r{_bar(done, total)}", end="", flush=True
    )
    result = await run_recap(
        DemoSource(hours=args.hours, poison_rate=args.poison),
        DemoLLM(),
        _build_config(args),
        on_progress=on_progress,
        scorer=scorer,
        corrector=corrector,
        quality_config=quality_config,
    )
    print("\n")

    if result.incremental_recap:
        print("=== 增量局部摘要（分片完成 80% 时异步生成） ===")
        print(result.incremental_recap[:400], "...\n")

    print("=== 最终概括 ===")
    print(result.recap, "\n")
    s = result.stats
    print("=== 统计 ===")
    line = (
        f"分片数: {s.shard_count} | 压缩轮次: {s.compression_rounds} | "
        f"输入 {s.chars_in} 字符 -> 输出 {s.chars_out} 字符 "
        f"(压缩到 {s.chars_out / max(s.chars_in, 1):.1%})"
    )
    if s.avg_quality is not None:
        line += f" | 修正 {s.corrected_count} 句 | 平均质量 {s.avg_quality:.2f}"
    print(line)


def _print_report(report: EvalReport) -> bool:
    """打印成绩单，返回是否达到全部基线。

    基线数值与"谁不达标"的判断都由监控层给出，这里只负责展示。
    """
    print("=== 评测成绩单 ===")
    print(f"考卷: {report.suite} | 判定阈值: {report.threshold:.2f}")

    if report.scorer is not None:
        metrics = report.scorer
        print(f"用例数: {metrics.case_count}")

    checks = baseline_checks(report)
    for check in checks:
        mark = "✓" if check.passed else "✗ 低于基线"
        print(f"{check.name}: {check.measured:.1%}   基线 ≥ {check.required:.0%}   {mark}")

    if report.scorer is not None:
        metrics = report.scorer
        print(
            "分类别准确率: "
            + " | ".join(
                f"{category} {value:.0%}"
                for category, value in metrics.per_category_accuracy.items()
            )
        )
        if metrics.misses:
            print(f"错题 {len(metrics.misses)} 条: " + "、".join(metrics.misses))
        else:
            print("错题: 无")

    passed = all(check.passed for check in checks)
    print("结论: " + ("达到基线 ✓" if passed else "未达基线 ✗"))
    return passed


async def run_eval_command(args: argparse.Namespace) -> int:
    config = QualityConfig() if args.threshold is None else QualityConfig(threshold=args.threshold)
    report = await run_eval(args.suite, config)
    return 0 if _print_report(report) else 1


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "eval":
        sys.exit(asyncio.run(run_eval_command(args)))
    asyncio.run(run_demo(args))


if __name__ == "__main__":
    main()
