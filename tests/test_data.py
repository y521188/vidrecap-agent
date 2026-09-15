"""数据层测试：可调参数默认值只在一处声明，非法值必须被挡住。"""

import pytest

from vidrecap.data.api import CompressionStep, PipelineConfig, QualityConfig, SentenceScore


def test_defaults_live_in_one_place():
    cfg = PipelineConfig()
    assert cfg.shard_seconds == 600.0
    assert cfg.overlap_seconds == 30.0
    assert cfg.max_concurrency == 8
    assert cfg.context_limit == 4000
    assert cfg.incremental_at == 0.8


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shard_seconds": 0},
        {"shard_seconds": -10},
        {"overlap_seconds": -1},
        {"overlap_seconds": 600, "shard_seconds": 600},  # 缓冲区不能吞掉整个责任区
        {"max_concurrency": 0},
        {"context_limit": 0},
        {"incremental_at": 0},
        {"incremental_at": 1.5},
    ],
)
def test_invalid_config_rejected(kwargs):
    with pytest.raises(ValueError):
        PipelineConfig(**kwargs)


def test_compression_step_carries_planned_text():
    step = CompressionStep(action="pass", left="原文")
    assert step.left == "原文"
    assert step.right == ""


def test_quality_defaults_match_the_agreed_weights():
    cfg = QualityConfig()
    assert cfg.clarity_weight == 0.5
    assert cfg.fluency_weight == 0.3
    assert cfg.completeness_weight == 0.2
    assert cfg.threshold == 0.7


@pytest.mark.parametrize(
    "kwargs",
    [
        {"clarity_weight": 0.5, "fluency_weight": 0.5, "completeness_weight": 0.5},
        {"threshold": 0},
        {"threshold": 1.5},
    ],
)
def test_invalid_quality_config_rejected(kwargs):
    with pytest.raises(ValueError):
        QualityConfig(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"clarity": 1.5, "fluency": 0.5, "completeness": 0.5, "total": 0.5},
        {"clarity": 0.5, "fluency": -0.1, "completeness": 0.5, "total": 0.5},
        {"clarity": 0.5, "fluency": 0.5, "completeness": 0.5, "total": 2.0},
    ],
)
def test_sentence_score_stays_in_range(kwargs):
    with pytest.raises(ValueError):
        SentenceScore(**kwargs)
