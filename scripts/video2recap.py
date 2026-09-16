"""外挂脚本：视频 → 字幕（SRT）→ 概括，一条命令跑完全程。

为什么是"外挂"而不是包内适配器：语音识别的开源许可证有红线
（docs/REUSE.md 第七节）——faster-whisper 连同模型权重都是 MIT，可以放心用，
但它是个重依赖（首次运行要下模型），不该成为 vidrecap 包的安装负担；
whisper-timestamped 是 AGPL，坚决不碰。所以本脚本独立于 vidrecap 包，
faster-whisper 由使用者按需自行安装，没装时给出友好提示。

分工：本脚本只干"看视频变字幕"这一件事，字幕生成后立即转交
`python -m vidrecap demo --srt ...`——概括链路（分片、质检、修正、统计）
全部复用包内现成逻辑，脚本不为它重复一行代码。

用法：
    python scripts/video2recap.py 节目.mp4 --llm openai --model deepseek-chat

- ``--whisper-model tiny/base/small/medium``（默认 small，首次运行自动下模型）
- ``--language zh``（默认中文；中文识别会附带提示让模型带上标点）
- 其余参数原样转交给 ``vidrecap demo``（如 ``--llm``、``--model``、``--store``）；
  什么都不加就是离线假模型，零 Key 先试流程
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _ts(seconds: float) -> str:
    """秒 → SRT 时间轴（``00:00:01,234``）。"""
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(entries, path: str | Path) -> None:
    """把 (开始秒, 结束秒, 文本) 序列写成标准 SRT 文件，空段跳过、序号连续。"""
    blocks: list[str] = []
    for start, end, text in entries:
        text = text.strip()
        if not text:
            continue
        blocks.append(f"{len(blocks) + 1}\n{_ts(start)} --> {_ts(end)}\n{text}\n")
    Path(path).write_text("\n".join(blocks), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video2recap", description="视频 → 字幕 → 概括，一条龙外挂脚本"
    )
    parser.add_argument("video", help="视频或音频文件路径")
    parser.add_argument(
        "--whisper-model",
        default="small",
        help="faster-whisper 模型档（tiny/base/small/medium，默认 small）",
    )
    parser.add_argument("--language", default="zh", help="说话语言（默认中文）")
    parser.add_argument(
        "--srt-out", default=None, help="字幕输出路径（默认与视频同名的 .srt）"
    )
    return parser


def transcribe_to_srt(video: str, srt_path: str, model_size: str, language: str) -> None:
    """本地语音识别，产出带时间轴的 SRT。首次运行会先下载模型文件。"""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "缺少语音识别库：请先 pip install faster-whisper"
            "（MIT 许可证、含模型权重；按需自装，不进 vidrecap 的依赖）"
        ) from exc

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    prompt = "以下是普通话的句子，请带上标点。" if language == "zh" else None
    segments, _info = model.transcribe(
        video, language=language, vad_filter=True, initial_prompt=prompt
    )
    write_srt(((seg.start, seg.end, seg.text) for seg in segments), srt_path)


def main(argv: list[str] | None = None) -> None:
    args, forwarded = build_parser().parse_known_args(argv)
    video = Path(args.video)
    if not video.exists():
        raise SystemExit(f"文件不存在: {video}")
    srt_path = args.srt_out or str(video.with_suffix(".srt"))

    print(f"[1/2] 识别中（模型 {args.whisper_model}，首次运行会先下载模型）……")
    transcribe_to_srt(str(video), srt_path, args.whisper_model, args.language)
    print(f"[1/2] 字幕已生成: {srt_path}")

    cmd = [sys.executable, "-m", "vidrecap", "demo", "--srt", srt_path, *forwarded]
    print(f"[2/2] 转交概括流水线: {' '.join(cmd)}")
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
