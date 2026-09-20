"""说话人分离适配器（sherpa-onnx 可选装配）：声纹聚类 + 字幕贴说话人标签。"""

from vidrecap.external.adapters.diarize.separate import (
    SherpaDiarizer,
    apply_speakers,
)

__all__ = ["SherpaDiarizer", "apply_speakers"]
