import json

import pytest

from evaluation.benchmark import (
    RunOutcome,
    budget_aware_scripted,
    compare_strategies,
    deterministic_baseline,
    grade_summary,
    load_cases,
    single_model_baseline,
)


def test_fixture_is_versioned_and_covers_failures():
    cases = load_cases()
    assert len(cases) == 6
    assert {case["scenario"] for case in cases} == {
        "normal", "malformed_primary", "rate_limited_primary"
    }
    assert any(case["id"] == "empty_inbox" for case in cases)
    assert any(case["id"] == "duplicate_notification" for case in cases)


def test_unknown_fixture_version_rejected(tmp_path):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({"version": 99, "cases": []}))
    with pytest.raises(ValueError, match="version"):
        load_cases(path)


@pytest.mark.asyncio
async def test_deterministic_baseline_meets_fixture_quality():
    report = await compare_strategies({"deterministic_baseline": deterministic_baseline})
    results = {row["case_id"]: row for row in report["results"]}
    assert results["empty_inbox"]["success"] is True
    assert results["mixed_repositories"]["success"] is True
    assert results["duplicate_notification"]["success"] is True
    assert report["summary"]["deterministic_baseline"]["task_success_rate"] == 1.0
    assert report["summary"]["deterministic_baseline"]["total_tokens"] == 0


@pytest.mark.asyncio
async def test_comparison_uses_same_cases_and_counts_fallbacks():
    cases = load_cases()[:2]

    async def successful(case):
        baseline = await deterministic_baseline(case)
        return RunOutcome(baseline.summary, model="scripted", tokens=12, fallback_used=True)

    report = await compare_strategies({"baseline": deterministic_baseline, "budget": successful}, cases)
    assert [row["case_id"] for row in report["results"]] == [
        "empty_inbox", "empty_inbox", "review_request", "review_request"
    ]
    assert report["summary"]["budget"]["total_tokens"] == 24
    assert report["summary"]["budget"]["fallback_recoveries"] == 2
    assert report["summary"]["budget"]["task_success_rate"] == 1.0


def test_grader_requires_links_and_expected_counts():
    case = next(case for case in load_cases() if case["id"] == "review_request")
    failures = grade_summary(case, "Review parser change Review parser change")
    assert any("Missing" in failure for failure in failures)
    assert any("Occurrences" in failure for failure in failures)


@pytest.mark.asyncio
async def test_scripted_comparison_exercises_actual_router():
    report = await compare_strategies({
        "single": single_model_baseline,
        "budget": budget_aware_scripted,
    })
    baseline = report["summary"]["single"]
    budget = report["summary"]["budget"]
    assert baseline["task_success_rate"] == budget["task_success_rate"]
    assert budget["total_tokens"] < baseline["total_tokens"]
    assert budget["fallback_recoveries"] == 2
    assert budget["total_calls"] == baseline["total_calls"] + 1
    results = [row for row in report["results"] if row["strategy"] == "budget"]
    assert next(row for row in results if row["case_id"] == "malformed_output")["fallback_used"]
    assert next(row for row in results if row["case_id"] == "rate_limited")["fallback_used"]
