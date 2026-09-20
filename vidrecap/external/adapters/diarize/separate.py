"""说话人分离适配器：sherpa-onnx（可选依赖）——回答"谁在什么时间说话"。

原理：音频切窗 → 每窗算一个声纹嵌入（嗓音指纹）→ 指纹相近的窗聚成一堆，
同一堆就是同一个人。**只分出"说话人1/2/3"，不认真名**——把聚类对上真名
（声纹登记或按内容推断）是另一件事，见 docs/ROADMAP.md 远期路线。

sherpa-onnx 与 faster-whisper 同待遇：**可选依赖、不进 vidrecap 的依赖清单**，
没装时报错指路。两个模型文件首次使用时自动下载到 ``.vidrecap/models/``
（约 6MB + 40MB）；音频解码复用 ffmpeg 解析链（系统 ffmpeg → imageio-ffmpeg）。
"""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

# 模型直链（模块级常量，不经任何调用方输入）与下载域名白名单
_SEGMENTATION_URL = (
    "https://huggingface.co/csukuangfj/sherpa-onnx-pyannote-segmentation-3-0"
    "/resolve/main/model.onnx"
)
_EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
)
_MODELS_DIR = Path(".vidrecap") / "models"
_ALLOWED_HOST_SUFFIXES = ("huggingface.co", "hf.co", "github.com", "githubusercontent.com")


def _url_allowed(url: str) -> bool:
    """下载只走 https、只认开源托管白名单域名（含子域）。"""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_HOST_SUFFIXES)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁用自动跟随重定向——每一跳都要回到白名单校验再走。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _download(url: str, dest: Path, hops_left: int = 5) -> None:
    if not _url_allowed(url):
        raise ValueError(f"模型下载地址不在白名单内: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "vidrecap"})
    try:
        response = _OPENER.open(request, timeout=120)
    except urllib.error.HTTPError as exc:  # 3xx 在这里冒出来（自动跟随已关）
        location = exc.headers.get("Location", "")
        if hops_left <= 0 or not location or not _url_allowed(location):
            raise ValueError(f"模型下载重定向越界: {url} -> {location}") from exc
        return _download(location, dest, hops_left - 1)
    with response, dest.with_suffix(dest.suffix + ".part").open("wb") as fh:
        while chunk := response.read(1024 * 1024):
            fh.write(chunk)
    dest.with_suffix(dest.suffix + ".part").replace(dest)


def _ensure_model(url: str, dest: Path) -> Path:
    """模型缺失才下载；先写 .part 再原子改名，半截文件不会冒充成品。"""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    _download(url, dest)
    return dest


def _decode_mono_16k(path: str | Path):
    """ffmpeg 解码成 16kHz 单声道，读成 float32 样本（sherpa 要的口径）。"""
    import numpy as np

    from vidrecap.external.adapters.visual.frames import ffmpeg_exe  # 同层直引免绕环：窗口会反向引本模块

    decoded = _MODELS_DIR.parent / "tmp" / "diarize_input.wav"
    decoded.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-y",
            str(decoded),
        ],
        check=True,
    )
    with wave.open(str(decoded)) as handle:
        raw = handle.readframes(handle.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


class SherpaDiarizer:
    """实现 external.protocols.Diarizer（形状对上即可，无需继承）。

    模型与配置延迟到第一次分离才构造；threshold 是聚类松紧
    （越大越容易拆成多人，越小越容易并成一人，0.5 是官方默认）。
    """

    def __init__(self, threshold: float = 0.5) -> None:
        self._threshold = threshold
        self._pipeline = None

    def diarize(
        self,
        path: str | Path,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[tuple[float, float, str]]:
        try:
            import sherpa_onnx
        except ImportError as exc:  # 指路，而不是让调用方对着栈猜
            raise RuntimeError(
                "服务端未安装说话人分离库：pip install sherpa-onnx 后重启服务"
                "（Apache-2.0；按需自装，不进 vidrecap 的依赖）"
            ) from exc

        samples = _decode_mono_16k(path)
        if self._pipeline is None:
            segmentation = _ensure_model(
                _SEGMENTATION_URL, _MODELS_DIR / "pyannote-segmentation-3-0.onnx"
            )
            embedding = _ensure_model(
                _EMBEDDING_URL, _MODELS_DIR / "3dspeaker-eres2net.onnx"
            )
            config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                        model=str(segmentation)
                    ),
                    num_threads=1,
                ),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(embedding), num_threads=1
                ),
                clustering=sherpa_onnx.FastClusteringConfig(threshold=self._threshold),
            )
            self._pipeline = sherpa_onnx.OfflineSpeakerDiarization(config)

        def _callback(done: int, total: int) -> int:
            if on_progress is not None:
                on_progress(done, total)
            return 0  # 返回非零会中止，这里永远继续

        result = self._pipeline.process(samples, _callback)
        return [
            (float(seg.start), float(seg.end), f"说话人{int(seg.speaker) + 1}")
            for seg in result.sort_by_start_time()
        ]


def apply_speakers(
    entries: list[tuple[float, float, str]],
    turns: list[tuple[float, float, str]],
) -> list[tuple[float, float, str]]:
    """给字幕条目贴说话人标签：谁与这句的重叠时间最长，这句就算谁说的。

    贴不上的（分离没覆盖到）保持原样；已带 ``〖`` 画面前缀或说话人前缀的
    行不再重复贴——画面行没有"说话人"，重复贴会出现"说话人1：〖画面〗…"的怪相。
    """
    labeled: list[tuple[float, float, str]] = []
    for start, end, text in entries:
        best: str | None = None
        best_overlap = 0.0
        for turn_start, turn_end, speaker in turns:
            overlap = min(end, turn_end) - max(start, turn_start)
            if overlap > best_overlap:
                best_overlap, best = overlap, speaker
        if best is not None and not text.startswith(("〖", "说话人")):
            text = f"{best}：{text}"
        labeled.append((start, end, text))
    return labeled
