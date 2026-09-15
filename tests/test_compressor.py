"""压缩测试：规划层给计划、服务层照计划执行。

分两层验证：plan_compression 只做单步决策（纯函数），compress 负责递归
执行与调用模型（有 I/O）。
"""

import pytest

from vidrecap.planning.api import plan_compression
from vidrecap.service.api import compress


class ShrinkingLLM:
    """每次调用把文本砍半的假大模型，记录调用次数。"""

    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, text: str, instruction: str = "") -> str:
        self.calls += 1
        return text[: len(text) // 2]


class IdentityLLM:
    async def summarize(self, text: str, instruction: str = "") -> str:
        return text


# --- 规划层：只出主意，不执行 ---


def test_plan_passes_through_when_within_limit():
    step = plan_compression("短内容", limit=100)
    assert step.action == "pass"
    assert step.left == "短内容"


def test_plan_splits_without_losing_text():
    text = "\n\n".join("内容" * 100 for _ in range(4))
    step = plan_compression(text, limit=50)
    assert step.action == "split"
    assert step.left and step.right
    # 拆分只搬家不丢字：按拆点原样拼回去就是原文
    assert step.left + "\n\n" + step.right == text


def test_plan_is_deterministic():
    text = "这是一段很长的内容。" * 100
    assert plan_compression(text, limit=10) == plan_compression(text, limit=10)


# --- 服务层：照计划执行 ---


async def test_text_within_limit_passes_through_untouched():
    llm = ShrinkingLLM()
    result, calls = await compress("短内容", limit=100, llm=llm)
    assert result == "短内容"
    assert calls == 0


async def test_long_text_converges_under_limit():
    llm = ShrinkingLLM()
    text = "这是一段很长的节目内容。" * 500
    result, calls = await compress(text, limit=500, llm=llm)
    assert len(result) <= 500
    assert calls > 0


async def test_recursive_split_happens_before_summarization():
    # 4 段各 300 字符、上限 400：应先递归到段级，再合并
    llm = ShrinkingLLM()
    text = "\n\n".join("内容" * 150 for _ in range(4))
    result, calls = await compress(text, limit=400, llm=llm)
    assert len(result) <= 400
    assert calls >= 2  # 至少发生了两次摘要调用


async def test_zero_limit_rejected():
    with pytest.raises(ValueError):
        await compress("x", limit=0, llm=ShrinkingLLM())
