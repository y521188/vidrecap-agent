"""说话人分离适配器测试：贴标签纯函数、插座形状、下载白名单、真实分离（装了才跑）。"""

from pathlib import Path

import pytest

from vidrecap.external.adapters.diarize import separate as separate_module
from vidrecap.external.adapters.diarize.separate import (
    SherpaDiarizer,
    _url_allowed,
    apply_speakers,
)
from vidrecap.external.api import Diarizer


def test_apply_speakers_labels_by_longest_overlap():
    entries = [(0.0, 2.0, "你好。"), (2.0, 4.0, "谢谢。"), (10.0, 12.0, "旁白没分到。")]
    turns = [(0.0, 2.5, "说话人1"), (2.5, 5.0, "说话人2")]
    labeled = apply_speakers(entries, turns)
    assert labeled[0][2] == "说话人1：你好。"
    assert labeled[1][2] == "说话人2：谢谢。"
    assert labeled[2][2] == "旁白没分到。"  # 分离没覆盖到的保持原样


def test_apply_speakers_skips_visual_and_prefixed_lines():
    entries = [(0.0, 2.0, "〖画面〗城市夜景。"), (2.0, 4.0, "说话人1：已贴过。")]
    labeled = apply_speakers(entries, [(0.0, 4.0, "说话人9")])
    assert labeled[0][2] == "〖画面〗城市夜景。"  # 画面行没有"说话人"
    assert labeled[1][2] == "说话人1：已贴过。"  # 不重复贴


def test_diarizer_satisfies_protocol():
    assert isinstance(SherpaDiarizer(), Diarizer)


def test_download_allowlist_blocks_private_and_http():
    assert _url_allowed("https://huggingface.co/csukuangfj/x/resolve/main/model.onnx")
    assert _url_allowed("https://objects.githubusercontent.com/some/asset")
    assert not _url_allowed("http://huggingface.co/model.onnx")  # 只走 https
    assert not _url_allowed("https://127.0.0.1/model.onnx")  # 环回不许
    assert not _url_allowed("https://internal.corp/model.onnx")  # 白名单外不许
    assert not _url_allowed("file:///etc/passwd")


def _real_stack_available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401

    except ImportError:
        return False
    models = Path(".vidrecap/models")
    return (models / "pyannote-segmentation-3-0.onnx").exists() and (
        models / "3dspeaker-eres2net.onnx"
    ).exists()


@pytest.mark.skipif(
    not _real_stack_available(), reason="未装 sherpa-onnx / 模型未就位时跳过真实分离"
)
def test_real_diarization_on_silent_clip(tmp_path):
    """静音片走通全链（解码→模型→聚类），预期没有说话人分段——验证的是管线不是效果。"""
    import subprocess

    from vidrecap.external.api import ffmpeg_exe

    silent = tmp_path / "silence.wav"
    subprocess.run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=duration=2:sample_rate=16000",
            "-ac", "1", "-y", str(silent),
        ],
        check=True,
    )
    turns = SherpaDiarizer().diarize(silent)
    assert isinstance(turns, list)  # 静音：0 段也算正常结果
    assert all(turn[2].startswith("说话人") for turn in turns)
