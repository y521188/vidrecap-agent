"""SenseVoice 识别适配器：方言与多语种（中/粤/英/日/韩）的 Transcriber 实现。

背景：whisper 对中文方言（粤语、四川话等）识别率断崖式下跌；SenseVoice
（FunASR 生态，Apache-2.0）的中文/粤语文本准确率显著更好。经 sherpa-onnx
的 ONNX 导出运行——**sherpa-onnx 是既有可选依赖**（说话人分离已在用），
本适配器零新增依赖。

口径：

- 模型三件（SenseVoice int8 约 230MB、tokens、Silero VAD）首次使用自动
  下载到 ``.vidrecap/models/``，下载走与说话人分离同一条白名单通道
  （复用 diarize 模块的校验函数）；
- SenseVoice 不出时间戳，所以先 Silero VAD 切人声段、逐段识别，段起点即
  时间戳——顺带把音乐/静音挡在识别之外；
- VAD 的手动窗口循环是低层接口（``is_speech``）：窗口过窗，静音累计超过
  ``min_silence_duration`` 才断段，段内样本原样拼接（不丢中间静音，语流自然）；
- 语言参数传 SenseVoice 的语言令牌（zh / yue / en / ja / ko，空=自动），
  与页面的语言下拉映射；``use_itn`` 开着（口语数字转阿拉伯数字）。
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Callable

from vidrecap.external.adapters.diarize.separate import (
    _MODELS_DIR,
    _decode_mono_16k,
    _ensure_model,
)

_SAMPLE_RATE = 16_000

_SEGMENTATION_REPO = "https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main"
_MODEL_URL = f"{_SEGMENTATION_REPO}/model.int8.onnx"
_TOKENS_URL = f"{_SEGMENTATION_REPO}/tokens.txt"
_VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"

# 页面语言下拉的值 → SenseVoice 语言令牌（空串=模型自动判）
_LANGUAGE_TOKENS = {"zh": "zh", "yue": "yue", "en": "en", "auto": ""}


class SenseVoiceTranscriber:
    """实现 external.protocols.Transcriber（形状对上即可，无需继承）。"""

    def __init__(
        self,
        language: str = "auto",
        min_silence_seconds: float = 0.5,
    ) -> None:
        self._language = _LANGUAGE_TOKENS.get(language, "")
        self._min_silence_seconds = min_silence_seconds
        self._recognizer = None
        self._vad = None

    def _ensure_pipeline(self) -> None:
        import sherpa_onnx

        if self._recognizer is not None:
            return
        model = _ensure_model(_MODEL_URL, _MODELS_DIR / "sensevoice-model.int8.onnx")
        tokens = _ensure_model(_TOKENS_URL, _MODELS_DIR / "sensevoice-tokens.txt")
        vad_model = _ensure_model(_VAD_URL, _MODELS_DIR / "silero_vad.onnx")
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model),
            tokens=str(tokens),
            use_itn=True,
            language=self._language,
        )
        self._vad = sherpa_onnx.VadModel.create(
            sherpa_onnx.VadModelConfig(
                silero_vad=sherpa_onnx.SileroVadModelConfig(model=str(vad_model)),
                sample_rate=_SAMPLE_RATE,
            )
        )

    def _speech_segments(self, samples) -> list[tuple[int, int]]:
        """Silero VAD 切人声段，返回 [(样本起点, 样本终点)]（采样点口径）。"""
        window = self._vad.window_size()
        min_silence = self._vad.min_silence_duration_samples()
        min_speech = self._vad.min_speech_duration_samples()
        segments: list[tuple[int, int]] = []
        in_speech = False
        speech_start = 0
        silence_run = 0
        for offset in range(0, len(samples) - window + 1, window):
            if self._vad.is_speech(samples[offset : offset + window]):
                silence_run = 0
                if not in_speech:
                    in_speech, speech_start = True, offset
            elif in_speech:
                silence_run += window
                if silence_run >= min_silence:
                    if offset + window - speech_start >= min_speech:
                        segments.append((speech_start, offset + window))
                    in_speech = False
        if in_speech:  # 收尾：说到文件末尾的段
            segments.append((speech_start, len(samples)))
        return segments

    def transcribe(
        self,
        path: str | Path,
        language: str | None = None,
        on_progress: Callable[[float, float], None] | None = None,
    ) -> list[tuple[float, float, str]]:
        try:
            import sherpa_onnx
        except ImportError as exc:  # 指路，而不是让调用方对着栈猜
            raise RuntimeError(
                "服务端未安装识别运行库：pip install sherpa-onnx 后重启服务"
                "（Apache-2.0；按需自装，不进 vidrecap 的依赖）"
            ) from exc
        del sherpa_onnx  # 仅作可用性探测；实际用延迟构造的流水线

        self._ensure_pipeline()
        samples = _decode_mono_16k(path)
        entries: list[tuple[float, float, str]] = []
        for start, end in self._speech_segments(samples):
            chunk = samples[start:end]
            stream = self._recognizer.create_stream()
            stream.accept_waveform(_SAMPLE_RATE, chunk)
            self._recognizer.decode_stream(stream)
            text = stream.result.text.strip()
            if text:  # 空结果丢弃，不让空行污染时间线
                entries.append((start / _SAMPLE_RATE, end / _SAMPLE_RATE, text))
            if on_progress is not None:
                on_progress(end / _SAMPLE_RATE, len(samples) / _SAMPLE_RATE)
        return entries
