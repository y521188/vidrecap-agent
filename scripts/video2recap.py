"""外挂脚本：视频 → 字幕（+ 可选画面）→ 概括，一条命令跑完全程。

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
- ``--visual`` 抽帧后请视觉模型描述"谁在做什么"，与语音字幕合并成一条时间线
  （默认每 120 秒一帧、最多 200 帧；**按帧计费**，运行前会打印帧数供你估算）
- 其余参数原样转交给 ``vidrecap demo``（如 ``--llm``、``--model``、``--store``）；
  什么都不加就是离线假模型，零 Key 先试流程
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

from vidrecap.external.api import OpenAICompatibleLLM

_VISUAL_PREFIX = "〖画面〗"
_VISION_PROMPT = "用一句话描述这张视频画面：谁在做什么、画面上有什么关键文字。不超过 40 字。"


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
        prog="video2recap", description="视频 → 字幕（+ 画面）→ 概括，一条龙外挂脚本"
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
    parser.add_argument(
        "--visual", action="store_true", help="抽帧请视觉模型描述画面，与语音字幕合并"
    )
    parser.add_argument(
        "--frame-interval",
        type=float,
        default=120.0,
        help="抽帧间隔秒数（默认 120；越小越密越贵）",
    )
    parser.add_argument(
        "--max-frames", type=int, default=200, help="最多描述多少帧（默认 200，成本上限）"
    )
    parser.add_argument(
        "--vision-model",
        default=None,
        help="视觉模型名（默认看环境变量 OPENAI_VISION_MODEL，再退回 OPENAI_MODEL）",
    )
    return parser


def transcribe(video: str, model_size: str, language: str) -> list[tuple[float, float, str]]:
    """本地语音识别，产出 (开始秒, 结束秒, 文本)。首次运行会先下载模型文件。"""
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
    return [(seg.start, seg.end, seg.text) for seg in segments]


def pick_frames(
    video: str, out_dir: Path, interval: float, max_frames: int
) -> list[tuple[float, Path]]:
    """用 ffmpeg 均匀抽帧。

    时间戳按"序号 × 间隔"推算（fps 滤镜就是从 0 开始等间隔取），够对齐用；
    画面切换加密抽帧留待需要时再接场景检测（见 docs/REUSE.md 的 PySceneDetect）。
    """
    if shutil.which("ffmpeg") is None:
        raise SystemExit("缺少 ffmpeg：画面抽帧需要它（装好后重试；不加 --visual 则不需要）")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", video,
            "-vf", f"fps=1/{interval:g},scale=640:-2",
            "-frames:v", str(max_frames),
            "-y", str(out_dir / "frame_%05d.jpg"),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("抽帧失败：检查视频文件能否被 ffmpeg 读取")
    frames = sorted(out_dir.glob("frame_*.jpg"))
    return [(index * interval, path) for index, path in enumerate(frames)]


def merge_tracks(
    voice_entries: list[tuple[float, float, str]],
    visual_events: list[tuple[float, str]],
    event_seconds: float = 4.0,
) -> list[tuple[float, float, str]]:
    """把画面事件并进语音字幕轨：画面行带前缀、占一个短时段，整体按时间排序。"""
    merged = list(voice_entries)
    merged.extend(
        (start, start + event_seconds, f"{_VISUAL_PREFIX}{text}")
        for start, text in visual_events
    )
    return sorted(merged, key=lambda entry: entry[0])


async def describe_frames(
    frames: list[tuple[float, Path]], vision: OpenAICompatibleLLM, prompt: str
) -> list[tuple[float, str]]:
    """逐帧请视觉模型描述，空结果丢弃（不让空行污染时间线）。"""
    events: list[tuple[float, str]] = []
    for timestamp, path in frames:
        text = " ".join((await vision.describe_image(path.read_bytes(), prompt)).split())
        if text:
            events.append((timestamp, text))
    return events


def _vision_client(args: argparse.Namespace) -> OpenAICompatibleLLM:
    model = (
        args.vision_model
        or os.environ.get("OPENAI_VISION_MODEL")
        or os.environ.get("OPENAI_MODEL")
    )
    if not model:
        raise SystemExit(
            "画面分析需要视觉模型：用 --vision-model 或环境变量 OPENAI_VISION_MODEL 指定"
        )
    try:
        return OpenAICompatibleLLM(model=model)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def main(argv: list[str] | None = None) -> None:
    args, forwarded = build_parser().parse_known_args(argv)
    video = Path(args.video)
    if not video.exists():
        raise SystemExit(f"文件不存在: {video}")

    print(f"[1/3] 识别中（模型 {args.whisper_model}，首次运行会先下载模型）……")
    entries = transcribe(str(video), args.whisper_model, args.language)

    srt_path = args.srt_out or str(video.with_suffix(".srt"))
    if args.visual:
        frames = pick_frames(
            str(video),
            video.parent / f"{video.stem}.frames",
            args.frame_interval,
            args.max_frames,
        )
        print(
            f"[2/3] 画面描述：{len(frames)} 帧 × 每帧一次视觉调用"
            "（调 --frame-interval / --max-frames 可改密度与上限）……"
        )
        events = asyncio.run(
            describe_frames(frames, _vision_client(args), _VISION_PROMPT)
        )
        entries = merge_tracks(entries, events)
        srt_path = args.srt_out or str(video.with_suffix(".visual.srt"))
        print(f"[2/3] 画面事件 {len(events)} 条，已并入时间线（图帧留在 {video.stem}.frames/）")
    write_srt(entries, srt_path)
    print(f"字幕已生成: {srt_path}")

    cmd = [sys.executable, "-m", "vidrecap", "demo", "--srt", srt_path, *forwarded]
    print(f"[3/3] 转交概括流水线: {' '.join(cmd)}")
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
