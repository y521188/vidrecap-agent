"""SRT 字幕媒体源：把真实字幕文件接进 MediaSource 插座。

解析口径（只写在这里，别处不许再猜）：

- 字幕块用空行分隔；块内第一行若是纯数字（序号）则跳过——有没有都认；
- 时间轴形如 ``00:00:01,000 --> 00:00:04,000``，毫秒分隔符 ``,`` 与 ``.`` 都认；
- 时间轴认不出来直接报错：静默错位比不跑更糟；
- 块内多行文本拼成一条字幕；取窗口内容时块与块之间用换行连接。

时间窗取的是"与窗口有交集"的字幕（哪怕只压线半秒）——重叠缓冲区里
相邻分片由此拿到同一条跨窗字幕，与 demo 假源的按句取样语义对齐。
"""

from __future__ import annotations

import re
from pathlib import Path

_TIMESTAMP = re.compile(
    r"(\d{1,2}):([0-5]\d):([0-5]\d)[,.](\d{1,3})"
    r"\s*-->\s*"
    r"(\d{1,2}):([0-5]\d):([0-5]\d)[,.](\d{1,3})"
)


def _seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    """把 SRT 文本解析成 (开始秒, 结束秒, 字幕文本) 列表，保持文件顺序。"""
    entries: list[tuple[float, float, str]] = []
    # U+FEFF 不算空白符，strip() 吃不掉，得显式去掉
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if re.fullmatch(r"\d+", lines[0].strip()):  # 序号行，有就丢
            lines = lines[1:]
            if not lines:
                continue
        match = _TIMESTAMP.search(lines[0])
        if match is None:
            raise ValueError(f"无法识别的字幕时间轴: {lines[0]!r}")
        start = _seconds(*match.group(1, 2, 3, 4))
        end = _seconds(*match.group(5, 6, 7, 8))
        body = "".join(lines[1:])
        if body:
            entries.append((start, end, body))
    return entries


class SrtSource:
    """真实字幕源：实现 external.protocols.MediaSource（形状对上即可，无需继承）。"""

    def __init__(
        self, path: str | Path | None = None, *, text: str | None = None
    ) -> None:
        """字幕从哪来：磁盘文件路径，或请求体里直接带来的文本，二选一。"""
        if (path is None) == (text is None):
            raise ValueError("字幕源必须在 path 与 text 里二选一")
        if text is not None:
            raw = text
        else:
            # utf-8-sig 顺带吃掉 BOM，免得第一块开头混进看不见的字符
            raw = Path(path).read_text(encoding="utf-8-sig")
        self._entries = parse_srt(raw)
        if not self._entries:
            raise ValueError(
                f"字幕里没有可用内容: {path if path is not None else '(内联文本)'}"
            )

    def duration(self) -> float:
        return self._entries[-1][1]

    def content(self, start: float, end: float) -> str:
        return "\n".join(
            body for begin, finish, body in self._entries if begin < end and finish > start
        )
