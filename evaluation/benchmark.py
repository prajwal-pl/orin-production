"""Versioned, credential-free evaluation of GitHub notification summaries."""

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Awaitable, Callable
from unittest.mock import patch

from orchestration.agents import ModelCapabilities, ProviderResult, invoke_result
from orchestration.github import summarize_notifications
from orchestration.model_budget import ModelRecord, ModelRouter, TaskBudget
from orchestration.schema import NotificationSummary

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v1.json"


@dataclass(frozen=True)
class RunOutcome:
    summary: str | None
    model: str | None = None
    tokens: int | None = None
    calls: int | None = None
    fallback_used: bool = False
    status: str = "completed"


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    strategy: str
    success: bool
    status: str
    model: str | None
    tokens: int | None
    calls: int | None
    latency_ms: float
    fallback_used: bool
    failures: tuple[str, ...]


Strategy = Callable[[dict], Awaitable[RunOutcome]]


def load_cases(path: Path = FIXTURE_PATH) -> list[dict]:
    fixture = json.loads(path.read_text())
    if fixture["version"] != 1:
        raise ValueError("Unsupported evaluation fixture version")
    cases = fixture["cases"]
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate evaluation case IDs")
    return cases


def grade_summary(case: dict, summary: str | None) -> tuple[str, ...]:
    if summary is None:
        return ("No summary returned",)
    failures = []
    for required in case["expected_contains"]:
        if required.casefold() not in summary.casefold():
            failures.append(f"Missing: {required}")
    for phrase, count in case.get("expected_occurrences", {}).items():
        actual = summary.count(phrase)
        if actual != count:
            failures.append(f"Occurrences of {phrase}: expected {count}, got {actual}")
    return tuple(failures)


async def measure(case: dict, strategy_name: str, strategy: Strategy) -> CaseResult:
    started = perf_counter()
    try:
        outcome = await strategy(case)
    except Exception as error:
        outcome = RunOutcome(summary=None, status=type(error).__name__)
    latency_ms = round((perf_counter() - started) * 1000, 3)
    failures = grade_summary(case, outcome.summary)
    return CaseResult(
        case_id=case["id"], strategy=strategy_name,
        success=outcome.status == "completed" and not failures,
        status=outcome.status, model=outcome.model, tokens=outcome.tokens,
        calls=outcome.calls,
        latency_ms=latency_ms, fallback_used=outcome.fallback_used,
        failures=failures,
    )


async def compare_strategies(strategies: dict[str, Strategy], cases: list[dict] | None = None) -> dict:
    cases = cases if cases is not None else load_cases()
    if not cases:
        raise ValueError("At least one evaluation case is required")
    results = []
    for case in cases:
        for name, strategy in strategies.items():
            results.append(await measure(case, name, strategy))
    summary = {}
    for name in strategies:
        subset = [result for result in results if result.strategy == name]
        known_tokens = [result.tokens for result in subset if result.tokens is not None]
        known_calls = [result.calls for result in subset if result.calls is not None]
        summary[name] = {
            "task_success_rate": round(sum(result.success for result in subset) / len(subset), 3),
            "total_tokens": sum(known_tokens) if len(known_tokens) == len(subset) else None,
            "total_calls": sum(known_calls) if len(known_calls) == len(subset) else None,
            "mean_latency_ms": round(sum(result.latency_ms for result in subset) / len(subset), 3),
            "fallback_recoveries": sum(result.success and result.fallback_used for result in subset),
        }
    return {"fixture_version": 1, "summary": summary, "results": [asdict(result) for result in results]}


async def deterministic_baseline(case: dict) -> RunOutcome:
    return RunOutcome(summary=summarize_notifications(case["notifications"]), tokens=0, calls=0)


class ScriptedBackend:
    """Fixture-only provider with simulated usage and delay."""

    def __init__(self, case: dict):
        self.case = case

    async def invoke(self, role: str, model: str, message: str) -> ProviderResult:
        if model == "scripted:small":
            await asyncio.sleep(0.002)
            if self.case["scenario"] == "malformed_primary":
                raise ValueError("Malformed scripted structured response")
            if self.case["scenario"] == "rate_limited_primary":
                error = RuntimeError("Scripted rate limit")
                error.status_code = 429
                raise error
            input_tokens, output_tokens = 12, 8
        else:
            await asyncio.sleep(0.004)
            input_tokens, output_tokens = 60, 40
        summary = summarize_notifications(self.case["notifications"])
        return ProviderResult(
            model=model,
            response=NotificationSummary(summary=summary),
            capabilities=ModelCapabilities(structured_output=True, tool_calling=None),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


async def scripted_model_strategy(case: dict, *, use_budget_router: bool) -> RunOutcome:
    """Exercise production routing with two controlled model profiles."""
    primary = "scripted:small" if use_budget_router else "scripted:large"
    fallback = "scripted:large" if use_budget_router else ""
    router = ModelRouter(records=[
        ModelRecord("scripted:small", complexity_level=1),
        ModelRecord("scripted:large", complexity_level=3),
    ])
    budget = TaskBudget(max_calls=3, max_tokens=500)
    with patch.dict(os.environ, {"ORIN_MODEL": primary, "ORIN_FALLBACK_MODEL": fallback}):
        result = await invoke_result(
            "notification_summarizer", json.dumps(case["notifications"]),
            backend=ScriptedBackend(case), router=router, budget=budget,
            complexity="simple", estimated_tokens=50,
        )
    return RunOutcome(
        summary=result.response.summary, model=result.model,
        tokens=budget.tokens_used, calls=budget.calls_used,
        fallback_used=len(set(result.attempted_models)) > 1,
    )


async def single_model_baseline(case: dict) -> RunOutcome:
    return await scripted_model_strategy(case, use_budget_router=False)


async def budget_aware_scripted(case: dict) -> RunOutcome:
    if not case["notifications"]:
        return await deterministic_baseline(case)
    return await scripted_model_strategy(case, use_budget_router=True)


async def main():
    report = await compare_strategies({
        "single_model_scripted": single_model_baseline,
        "budget_aware_scripted": budget_aware_scripted,
        "deterministic_baseline": deterministic_baseline,
    })
    report["measurement_note"] = (
        "Scripted model calls use fixed fixture token counts and delays. "
        "Latency includes local Python execution and is not provider latency."
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
