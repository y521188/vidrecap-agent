"""视觉描述实现：离线演示版（确定性占位，零 Key 可跑全链路）。

真实视觉走 OpenAICompatibleLLM.describe_image（OpenAI 兼容接口，外部层已有）；
演示版不读图片内容——它存在的意义是让"抽帧 → 描述 → 并轨"这条链没有
钥匙也能跑通、并且同样输入永远同样输出（确定性铁律），描述内容明确标注
"离线演示"，不冒充真实画面理解。
"""

from __future__ import annotations

_DEMO_DESCRIPTION = "（离线演示画面描述：此处应为由视觉模型生成的画面内容，填 Key 后为真实描述）"


class DemoVisionDescriber:
    """实现 external.protocols.VisionDescriber（形状对上即可，无需继承）。"""

    async def describe_image(self, image: bytes, prompt: str) -> str:
        return _DEMO_DESCRIPTION
