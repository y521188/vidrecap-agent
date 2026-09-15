"""假媒体源：按绝对时间生成确定性的"节目内容"，模拟 ASR+OCR 的输出。

内容是绝对时间的函数：同一个时间窗无论被哪个分片请求，拿到的文本
完全一致——这样重叠缓冲区里相邻分片拿到的确实是同一段话。
"""

from __future__ import annotations

import math
import random

SENTENCE_SECONDS = 8.0

_SUBJECTS = ["主持人", "嘉宾", "现场记者", "评论员", "栏目组", "受访观众", "数据分析师"]
_VERBS = ["分析了", "回顾了", "介绍了", "质疑了", "总结了", "展望了", "复盘了"]
_OBJECTS = [
    "节目制作流程",
    "媒体融合趋势",
    "短视频生态",
    "内容审核标准",
    "数据隐私保护",
    "平台推荐算法",
    "跨年晚会筹备",
    "纪录片拍摄幕后",
]


class DemoSource:
    """确定性的假"电视节目"：总时长 hours 小时，每 8 秒一句话。"""

    def __init__(self, hours: float = 3.0) -> None:
        if hours <= 0:
            raise ValueError("hours must be positive")
        self._duration = hours * 3600.0

    def duration(self) -> float:
        return self._duration

    def _sentence(self, i: int) -> str:
        # 每句话的随机源只取决于句子的序号，保证内容稳定可复现。
        # 这里刻意使用非加密随机数：demo 需要确定性输出，不用于任何安全用途，
        # 换成 secrets 反而会让结果不可复现、测试失去意义。
        rng = random.Random((i * 2654435761) % (2**32))
        return (
            f"第{i + 1}段：{rng.choice(_SUBJECTS)}{rng.choice(_VERBS)}"
            f"{rng.choice(_OBJECTS)}，并结合案例给出了详细说明。"
        )

    def content(self, start: float, end: float) -> str:
        first = int(start // SENTENCE_SECONDS)
        last = min(
            int(math.ceil(end / SENTENCE_SECONDS)),
            int(math.ceil(self._duration / SENTENCE_SECONDS)),
        )
        return "".join(self._sentence(i) for i in range(first, last))
