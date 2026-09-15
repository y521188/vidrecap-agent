"""二分递归压缩测试：短文本零调用、长文本收敛、递归正确触发。"""

import pytest

from vidrecap.core.compressor import compress


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
