"""命令行入口。

零依赖体验：python -m vidrecap demo
（使用内置离线假数据，不需要任何 API Key）
"""

from __future__ import annotations

import argparse
import asyncio

from .adapters.demo import DemoLLM, DemoSource
from .core.orchestrator import Orchestrator


def _bar(done: int, total: int, width: int = 28) -> str:
    filled = int(width * done / max(total, 1))
    return "[" + ">" * filled + "." * (width - filled) + f"] {done}/{total} 片段"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vidrecap", description="分治式长视频概括引擎"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="用内置离线假数据跑通全流程")
    demo.add_argument("--hours", type=float, default=3.0, help="模拟视频时长（小时）")
    demo.add_argument("--shard-seconds", type=float, default=600.0, help="分片时长（秒）")
    demo.add_argument("--overlap-seconds", type=float, default=30.0, help="重叠缓冲区（秒）")
    demo.add_argument("--concurrency", type=int, default=4, help="并行度")
    demo.add_argument(
        "--context-limit", type=int, default=1200, help="上下文字符上限，超限触发二分递归压缩"
    )
    return parser


async def run_demo(args: argparse.Namespace) -> None:
    print(
        f"模拟视频 {args.hours} 小时 | 分片 {args.shard_seconds:.0f}s | "
        f"重叠缓冲 {args.overlap_seconds:.0f}s | 并行 {args.concurrency} | "
        f"上下文上限 {args.context_limit} 字符"
    )
    orchestrator = Orchestrator(
        DemoLLM(),
        shard_seconds=args.shard_seconds,
        overlap_seconds=args.overlap_seconds,
        max_concurrency=args.concurrency,
        context_limit=args.context_limit,
        on_progress=lambda done, total: print(f"\r{_bar(done, total)}", end="", flush=True),
    )
    result = await orchestrator.run(DemoSource(hours=args.hours))
    print("\n")

    if result.incremental_recap:
        print("=== 增量局部摘要（分片完成 80% 时异步生成） ===")
        print(result.incremental_recap[:400], "...\n")

    print("=== 最终概括 ===")
    print(result.recap, "\n")
    s = result.stats
    print("=== 统计 ===")
    print(f"分片数: {s.shard_count} | 压缩轮次: {s.compression_rounds} | "
          f"输入 {s.chars_in} 字符 -> 输出 {s.chars_out} 字符 "
          f"(压缩到 {s.chars_out / max(s.chars_in, 1):.1%})")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    asyncio.run(run_demo(args))


if __name__ == "__main__":
    main()
