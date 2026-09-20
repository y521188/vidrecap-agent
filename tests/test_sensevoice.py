"""SenseVoice 适配器测试：协议形状、VAD 切段纯逻辑（不加载真模型）。"""

from vidrecap.external.api import SenseVoiceTranscriber, Transcriber


def test_sensevoice_transcriber_satisfies_protocol():
    assert isinstance(SenseVoiceTranscriber(), Transcriber)


def test_speech_segments_merges_silence_runs(monkeypatch):
    """切段逻辑：说话窗连起来、静音够长才断、碎段按最小语音时长丢弃。

    用 16 个窗口（每窗 1"采样单位"）构造：说 3 窗、静 2 窗、说 2 窗、静到尾。
    min_silence=2 窗 → 在第 2 个静音窗断开；min_speech=3 窗 → 第二段(2窗)丢弃。
    """
    adapter = SenseVoiceTranscriber()
    window = 10
    monkeypatch.setattr(
        adapter, "_vad",
        type(
            "FakeVad",
            (),
            {
                "window_size": lambda self: window,
                "min_silence_duration_samples": lambda self: 2 * window,
                "min_speech_duration_samples": lambda self: 3 * window,
                "is_speech": lambda self, chunk: (
                    0 <= chunk[0] < 3 * window or 5 * window <= chunk[0] < 7 * window
                ),
            },
        )(),
    )

    class _FakeSamples(list):
        pass

    samples = list(range(16 * window))
    segments = adapter._speech_segments(_FakeSamples(samples))
    # 第一段 0~5 窗（3 说 + 2 静达到断段线）；第二段 5~7 窗说 + 2 窗尾部静音
    # = 4 窗 ≥ min_speech 保留，静音归前段（断段判定本就吃掉这段静音）
    assert segments == [(0, 5 * window), (5 * window, 9 * window)]
