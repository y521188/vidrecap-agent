"""评测集与跑分测试：加载器、指标算法、成绩单、基线门槛。"""

from collections import Counter
from pathlib import Path

import pytest

from vidrecap.data.api import QualityConfig, SentenceScore
from vidrecap.monitor.api import (
    EvalReport,
    ScorerCase,
    ScorerGold,
    ScorerMetrics,
    load_scorer_cases,
    pairwise_ranking_accuracy,
    per_category_accuracy,
    run_eval,
    scorer_misses,
    threshold_accuracy,
)
from vidrecap.rules.api import (
    SCORER_MIN_PAIRWISE_RANKING_ACCURACY,
    SCORER_MIN_THRESHOLD_ACCURACY,
)
from vidrecap.user.api import main

# --- 内置考卷 ---


def test_builtin_exam_follows_the_planned_mix():
    cases = load_scorer_cases()
    assert len(cases) == 49
    assert Counter(case.category for case in cases) == {
        "clarity": 12,
        "fluency": 12,
        "completeness": 12,
        "mixed": 5,
        "good": 8,
    }
    assert all(case.context.strip() for case in cases), "每条用例都要有原文上下文"
    assert all(case.sentence.strip() for case in cases)


def test_category_mix_matches_the_documented_design():
    """三类病句各带 4 条好句对照；混合类全坏；好句类全好。

    好句对照是必需的——否则"见谁都给低分"的退化实现也能拿高分。
    """
    cases = load_scorer_cases()
    by_category: dict[str, list[bool]] = {}
    for case in cases:
        by_category.setdefault(case.category, []).append(case.gold.passed)

    for category in ("clarity", "fluency", "completeness"):
        labels = by_category[category]
        assert labels.count(False) == 8, category
        assert labels.count(True) == 4, category
    assert set(by_category["mixed"]) == {False}
    assert set(by_category["good"]) == {True}


def test_bad_cases_explain_what_is_wrong():
    """坏例要写清楚坏在哪，方便人工复核与后续出题。"""
    for case in load_scorer_cases():
        if not case.gold.passed:
            assert case.gold.note, f"{case.id} 缺少备注"


# --- 加载器 ---


def test_loader_accepts_crlf_comments_and_blank_lines(tmp_path: Path):
    path = tmp_path / "mini.jsonl"
    path.write_bytes(
        (
            "# 分组说明：下面是唯一的用例\r\n"
            "\r\n"
            '{"id":"a","category":"good","context":"原文","sentence":"句子。",'
            '"gold":{"passed":true}}\r\n'
        ).encode("utf-8")
    )
    assert [case.id for case in load_scorer_cases(path)] == ["a"]


def test_loader_reports_the_broken_line_number(tmp_path: Path):
    path = tmp_path / "broken.jsonl"
    path.write_text(
        '{"id":"a","category":"good","context":"原文","sentence":"句子。","gold":{"passed":true}}\n'
        "{ 这不合法\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="第 2 行"):
        load_scorer_cases(path)


def test_loader_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "dup.jsonl"
    line = '{"id":"same","category":"good","context":"原文","sentence":"句子。","gold":{"passed":true}}'
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="id 重复"):
        load_scorer_cases(path)


def test_loader_rejects_empty_exam(tmp_path: Path):
    path = tmp_path / "empty.jsonl"
    path.write_text("# 只有注释\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="没有任何用例"):
        load_scorer_cases(path)


def test_loader_reports_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_scorer_cases(tmp_path / "not-there.jsonl")


# --- 指标 ---


def _case(case_id: str, passed: bool, category: str = "fluency") -> ScorerCase:
    return ScorerCase(
        id=case_id,
        category=category,  # type: ignore[arg-type]
        context="原文",
        sentence="句子。",
        gold=ScorerGold(passed=passed),
    )


def _score(total: float, clarity: float = 1.0, fluency: float = 1.0, completeness: float = 1.0) -> SentenceScore:
    return SentenceScore(
        sentence="句子。",
        clarity=clarity,
        fluency=fluency,
        completeness=completeness,
        total=total,
    )


def test_threshold_accuracy_uses_the_gate_not_the_raw_total():
    """总分过线但单项严重不合格时闸门判不合格——考卷必须按闸门算。"""
    scores = [_score(0.85, fluency=0.4)]  # 总分 0.85 过线，但通顺度崩了
    assert threshold_accuracy([_case("a", passed=False)], scores) == 1.0
    assert threshold_accuracy([_case("a", passed=True, category="good")], scores) == 0.0


def test_pairwise_ranking_counts_every_pair():
    cases = [_case("g1", True, "good"), _case("g2", True, "good"), _case("b1", False)]
    scores = [_score(0.9), _score(0.95), _score(0.5)]
    assert pairwise_ranking_accuracy(cases, scores) == 1.0


def test_pairwise_ranking_gives_half_credit_for_ties():
    cases = [_case("g", True, "good"), _case("b", False)]
    assert pairwise_ranking_accuracy(cases, [_score(0.8), _score(0.8)]) == pytest.approx(0.5)


def test_pairwise_ranking_needs_both_good_and_bad():
    with pytest.raises(ValueError, match="好句与坏句"):
        pairwise_ranking_accuracy([_case("g", True, "good")], [_score(0.9)])


def test_per_category_accuracy_groups_by_category():
    cases = [
        _case("c1", False, "clarity"),
        _case("f1", False, "fluency"),
        _case("g1", True, "good"),
    ]
    scores = [_score(0.4, clarity=0.1), _score(0.4, fluency=0.1), _score(1.0)]
    assert per_category_accuracy(cases, scores) == {"clarity": 1.0, "fluency": 1.0, "good": 1.0}


def test_scorer_misses_lists_the_wrong_ids():
    cases = [_case("ok", False), _case("wrong", True, "good")]
    assert scorer_misses(cases, [_score(0.3), _score(0.3)]) == ["wrong"]


def test_metrics_reject_mismatched_lengths():
    with pytest.raises(ValueError, match="不一致"):
        threshold_accuracy([_case("a", True, "good")], [])


def test_metrics_reject_empty_exam():
    with pytest.raises(ValueError, match="考卷为空"):
        threshold_accuracy([], [])


# --- 跑分与基线门槛 ---


async def test_scorer_eval_report_has_every_section():
    report = await run_eval("scorer")
    assert report.suite == "scorer"
    assert report.threshold == QualityConfig().threshold
    assert report.scorer is not None
    assert report.scorer.case_count == 49
    assert report.scorer.per_category_accuracy
    assert report.corrector is None


async def test_eval_is_deterministic():
    assert await run_eval("scorer") == await run_eval("scorer")


async def test_unknown_suite_is_rejected():
    with pytest.raises(ValueError, match="未知的考卷"):
        await run_eval("nope")


async def test_heuristic_scorer_meets_the_threshold_accuracy_baseline():
    report = await run_eval("scorer")
    assert report.scorer is not None
    assert report.scorer.threshold_accuracy >= SCORER_MIN_THRESHOLD_ACCURACY, (
        f"阈值准确率退步：{report.scorer.threshold_accuracy:.1%}，"
        f"错题 {report.scorer.misses}"
    )


async def test_heuristic_scorer_meets_the_ranking_baseline():
    report = await run_eval("scorer")
    assert report.scorer is not None
    assert report.scorer.pairwise_ranking_accuracy >= SCORER_MIN_PAIRWISE_RANKING_ACCURACY


# --- 命令行 ---


def test_cli_eval_prints_the_report_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["eval"])
    assert excinfo.value.code == 0

    out = capsys.readouterr().out
    assert "评测成绩单" in out
    assert "阈值准确率" in out
    assert "排序正确率" in out
    assert "达到基线" in out


def test_cli_eval_exits_nonzero_when_below_baseline(monkeypatch, capsys):
    async def fake_run_eval(suite: str = "scorer", config=None) -> EvalReport:
        return EvalReport(
            suite=suite,
            threshold=0.7,
            scorer=ScorerMetrics(
                case_count=2,
                threshold_accuracy=0.5,
                pairwise_ranking_accuracy=0.5,
                per_category_accuracy={"clarity": 0.5},
                misses=["clarity-001"],
            ),
        )

    monkeypatch.setattr("vidrecap.user.cli.run_eval", fake_run_eval)

    with pytest.raises(SystemExit) as excinfo:
        main(["eval"])
    assert excinfo.value.code == 1

    out = capsys.readouterr().out
    assert "未达基线" in out
    assert "clarity-001" in out
