"""SRT 字幕适配器：真实字幕文件接入 MediaSource 插座。"""

from .source import SrtSource, parse_srt

__all__ = ["SrtSource", "parse_srt"]
