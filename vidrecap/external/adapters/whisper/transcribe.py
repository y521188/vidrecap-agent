"""faster-whisper 语音识别适配器：视频/音频文件 → 带时间轴的字幕条目。

faster-whisper（MIT）是**可选依赖**：不在 vidrecap 的依赖清单里，
装了才有视频入口，没装时报错指路——零依赖的底线不破。
模型文件延迟到第一次转写才加载（tiny 档约 75MB），服务启动零开销。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable


def _timestamp(seconds: float) -> str:
    """秒 → SRT 时间轴（``00:00:01,234``）。"""
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def to_srt_text(entries: list[tuple[float, float, str]]) -> str:
    """(开始秒, 结束秒, 文本) 列表 → 标准 SRT 文本，空段跳过、序号连续。"""
    blocks: list[str] = []
    for start, end, text in entries:
        text = text.strip()
        if not text:
            continue
        blocks.append(
            f"{len(blocks) + 1}\n{_timestamp(start)} --> {_timestamp(end)}\n{text}\n"
        )
    return "\n".join(blocks)


class WhisperTranscriber:
    """实现 external.protocols.Transcriber（形状对上即可，无需继承）。"""

    def __init__(self, model_size: str = "tiny") -> None:
        self._model_size = model_size
        self._model = None  # 模型延迟到第一次转写才加载

    def transcribe(
        self,
        path: str | Path,
        language: str | None = None,
        on_progress: Callable[[float, float], None] | None = None,
    ) -> list[tuple[float, float, str]]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # 指路，而不是让调用方对着栈猜
            raise RuntimeError(
                "服务端未安装语音识别库：pip install faster-whisper 后重启服务"
                "（MIT 许可证、含模型权重；按需自装，不进 vidrecap 的依赖）"
            ) from exc
        if self._model is None:
            self._model = WhisperModel(
                self._model_size, device="cpu", compute_type="int8"
            )
        # 中文给个初始提示让它带出标点（口径与 video2recap 外挂脚本一致）
        prompt = "以下是普通话的句子，请带上标点。" if language == "zh" else None
        segments, info = self._model.transcribe(
            str(path), language=language, vad_filter=True, initial_prompt=prompt
        )
        entries: list[tuple[float, float, str]] = []
        for segment in segments:
            entries.append((segment.start, segment.end, segment.text))
            if on_progress is not None:
                on_progress(segment.end, info.duration or 0.0)
        return entries
