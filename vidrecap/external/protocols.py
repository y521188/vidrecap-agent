"""能力抽象（插座）：核心引擎只认接口，不绑定任何厂商。

真实的大模型客户端、多模态识别服务、OCR 服务、质量打分器、句子修正器
都通过实现这里的 Protocol 接入，demo 里的是离线假实现。

实现方**不需要 import 本模块**——形状（方法签名）对得上即可，
一致性由测试用 runtime_checkable 的 isinstance 验证。
这样"规则层只依赖数据层"这条简单规矩才保得住。

本模块属于外部层实现部分（窗口在 external/api/），因为它包含类定义，
而 api 窗口只允许放转出语句。
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from vidrecap.data.api import SentenceScore, SpeakerProfile, SubtitleLine


@runtime_checkable
class LLMClient(Protocol):
    """大模型客户端的最小接口：给它一段文本，还你一份摘要。

    两级提示词（双重约束）：

    - ``system``：角色与规则（技能文件里的 System Prompt），实现方应作为
      system 消息发送；
    - ``instruction``：本次任务要求（用户自定义 Prompt）。

    两者都可为空，为空就不发对应的消息——老用法（只传 text）行为不变。
    """

    async def summarize(self, text: str, instruction: str = "", system: str = "") -> str: ...


@runtime_checkable
class MediaSource(Protocol):
    """媒体内容来源：给它一个时间段，返回该段的文本内容。

    真实实现对接多模态识别 + OCR 字幕；接口只关心"这段时间里说了什么"。
    """

    def duration(self) -> float: ...

    def content(self, start: float, end: float) -> str: ...


@runtime_checkable
class ContentCatalog(Protocol):
    """后台内容目录：给时间段，还"带说话人的字幕行 + 人物档案"。

    这是"Function Calling 调后台接口取字幕与人物标签"的落点：引擎在
    确定知道该取哪段数据的时候直接调适配器（确定性取数），不需要模型
    自己决定何时调工具——省 token、稳定、可复现。模型自主发起工具调用
    只作为可选演示形态，不进核心链路。

    接口是异步的：慢实现（HTTP、远程数据库）请在自己的适配器里用
    `asyncio.to_thread` 包一层——包装由适配器负责，与 QualityScorer 同规。
    """

    async def lines(self, start: float, end: float) -> list[SubtitleLine]: ...

    async def speaker_profiles(self) -> dict[str, SpeakerProfile]: ...


@runtime_checkable
class Transcriber(Protocol):
    """媒体转写插座：给视频/音频文件路径，还带时间轴的语音文本。

    语音识别是重依赖（模型文件上百 MB），永远是**可选装配**——
    没装配时服务端不开放视频入口，而不是装不动就悄悄降级。
    ``on_progress(已转写秒数, 总秒数)`` 是可选回调，长任务里定期调用以便推进度。
    """

    def transcribe(
        self,
        path: str,
        language: str | None = None,
        on_progress: Callable[[float, float], None] | None = None,
    ) -> list[tuple[float, float, str]]: ...


@runtime_checkable
class VisionDescriber(Protocol):
    """视觉描述插座：给一张图的字节和一句要求，还一句画面描述。

    真实实现走 OpenAI 兼容接口的视觉模型；离线演示版只做确定性占位，
    让"抽帧 → 描述 → 并轨"没有钥匙也能全链路跑通。
    """

    async def describe_image(self, image: bytes, prompt: str) -> str: ...


@runtime_checkable
class Diarizer(Protocol):
    """说话人分离插座：给媒体文件路径，还"谁在什么时间段说话"。

    返回 (开始秒, 结束秒, 说话人标签) 列表，标签形如"说话人1"——声纹聚类
    的产物，不含真名。on_progress(已处理块数, 总块数) 可选。

    speech_spans 是可选的"已知有人说话的时段"（来自转写）：给了就只对
    这些时段做聚类（whisperX 套路），音乐/静音段不进声纹——时间轴仍是
    原音频的，调用方无感。
    """

    def diarize(
        self,
        path: str,
        on_progress: Callable[[int, int], None] | None = None,
        speech_spans: list[tuple[float, float]] | None = None,
    ) -> list[tuple[float, float, str]]: ...


@runtime_checkable
class QualityScorer(Protocol):
    """质量打分：给一句话和它所在片段的原文，还一个三指标评分。

    打分分两档，别混用：

    - **默认档（规则层的启发式实现）必须确定性**：不调模型、不读时钟、不用随机，
      同样输入永远同样输出——CI 门槛与评测集靠它复现；
    - **模型档放外部层适配器**：模型推理有浮点噪声，做不到逐字节复现，
      所以只在"对比报告"里跑，不进 CI 门槛。

    接口是异步的：慢实现（要跑模型、要读文件）请在自己的适配器里用
    `asyncio.to_thread` 包一层——**包装由适配器负责**，服务层只管 await，
    不该知道谁快谁慢。纯启发式实现直接 `async def` 返回即可，没有额外开销。
    """

    async def score(self, sentence: str, context: str) -> SentenceScore: ...


@runtime_checkable
class SentenceCorrector(Protocol):
    """句子修正：给一句低于阈值的句子和它的原文，还一句改好的话。

    修正只许"补充与理顺"，不许引入原文没有的事实——是否越界由规则层的
    忠实性护栏判定，服务层据此决定采用还是回退原句。
    """

    async def correct(self, sentence: str, context: str) -> str: ...
