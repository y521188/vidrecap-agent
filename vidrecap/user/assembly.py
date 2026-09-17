"""适配器装配：用户层是唯一装配根，命令行与服务端共用这里的选型逻辑。

两处入口（命令行的 demo 子命令、服务端的 /recap）如果各写一份"用哪个模型、
用哪个媒体源、质检开不开"，迟早会漂。所以选型逻辑只此一处；
参数从哪来、出错怎么报（命令行退进程、服务端回 400）由各自调用方决定。

所有默认值仍只在数据层的 Config 里声明一次，这里只做覆盖（铁律 3）。
"""

from __future__ import annotations

from vidrecap.data.api import PipelineConfig, QualityConfig
from vidrecap.external.api import (
    DemoCorrector,
    DemoLLM,
    DemoSource,
    LLMClient,
    MediaSource,
    OpenAICompatibleLLM,
    QualityScorer,
    SentenceCorrector,
    SrtSource,
)
from vidrecap.rules.api import HeuristicScorer


def build_llm(kind: str, model: str | None = None) -> LLMClient:
    """按名字造模型客户端；kind="openai" 缺模型名时由适配器抛 ValueError。"""
    if kind == "openai":
        return OpenAICompatibleLLM(model=model)
    return DemoLLM()


def build_source(
    srt: str | None, hours: float, poison_rate: float = 0.0
) -> MediaSource:
    """有字幕文件走真实字幕源，否则用内置模拟数据（可注毒）。"""
    if srt:
        return SrtSource(srt)
    return DemoSource(hours=hours, poison_rate=poison_rate)


def build_config(
    *,
    shard_seconds: float | None = None,
    overlap_seconds: float | None = None,
    max_concurrency: int | None = None,
    context_limit: int | None = None,
    instruction: str | None = None,
    system_prompt: str | None = None,
) -> PipelineConfig:
    """把给定的覆盖项落到配置上；给 None 的字段沿用数据层默认值。"""
    overrides = {
        "shard_seconds": shard_seconds,
        "overlap_seconds": overlap_seconds,
        "max_concurrency": max_concurrency,
        "context_limit": context_limit,
        "summarize_instruction": instruction,
        "system_prompt": system_prompt,
    }
    return PipelineConfig(**{k: v for k, v in overrides.items() if v is not None})


def build_quality(
    *,
    disabled: bool = False,
    threshold: float | None = None,
    weights: list[float] | None = None,
) -> tuple[QualityScorer | None, SentenceCorrector | None, QualityConfig | None]:
    """质检回路：打分器、修正器与配置；disabled 时三者皆 None（老行为）。"""
    if disabled:
        return None, None, None
    overrides: dict[str, float] = {}
    if threshold is not None:
        overrides["threshold"] = threshold
    if weights is not None:
        overrides.update(
            clarity_weight=weights[0],
            fluency_weight=weights[1],
            completeness_weight=weights[2],
        )
    config = QualityConfig(**overrides) if overrides else None
    return HeuristicScorer(config), DemoCorrector(), config
