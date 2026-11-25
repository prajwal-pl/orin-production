from collections import deque

import pytest

from orchestration.agents import (
    ModelCapabilities,
    ProviderCallError,
    ProviderResult,
    invoke_result,
)
from orchestration.model_budget import BudgetExhausted, ModelRecord, ModelRouter, TaskBudget
from orchestration.runtime import Runtime
from orchestration.schema import NotificationSummary
from orchestration.store import TaskStore


class ScriptedBackend:
    def __init__(self, outcomes):
        self.outcomes = deque(outcomes)
        self.models = []

    async def invoke(self, role, model, message):
        self.models.append(model)
        outcome = self.outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return ProviderResult(model, NotificationSummary(summary=outcome),
                              ModelCapabilities(True, None), 7, 3)


def test_repeated_runtime_reads_do_not_rewrite_model_record(monkeypatch, tmp_path):
    monkeypatch.setenv("ORIN_MODEL", "scripted:primary")
    monkeypatch.setenv("ORIN_FALLBACK_MODEL", "")
    path = tmp_path / "orin.db"
    Runtime(path)

    def unexpected_write(self, record):
        raise AssertionError("Existing model records should not be rewritten on dashboard reads")

    monkeypatch.setattr(TaskStore, "save_model_record", unexpected_write)
    Runtime(path)


def models(monkeypatch):
    monkeypatch.setenv("ORIN_MODEL", "cheap")
    monkeypatch.setenv("ORIN_FALLBACK_MODEL", "strong")
    return ModelRouter([ModelRecord("cheap", context_window=1000, complexity_level=1),
                        ModelRecord("strong", context_window=10000, complexity_level=3)])


@pytest.mark.asyncio
async def test_complexity_routes_and_usage_is_observed(monkeypatch):
    router = models(monkeypatch)
    budget = TaskBudget(max_calls=3, max_tokens=100)
    backend = ScriptedBackend(["ok"])
    attempts = []
    result = await invoke_result("notification_summarizer", "inbox", backend,
                                 budget=budget, router=router, complexity="complex",
                                 estimated_tokens=40, observer=attempts.append)
    assert result.model == "strong"
    assert result.response.summary == "ok"
    assert result.attempted_models == ("strong",)
    assert (budget.calls_used, budget.tokens_used) == (1, 10)
    assert attempts[0].success and attempts[0].input_tokens == 7
    assert router.records["strong"].successful_calls == 1


@pytest.mark.asyncio
async def test_unknown_usage_keeps_conservative_reservation(monkeypatch):
    models(monkeypatch)

    class UnknownUsage:
        async def invoke(self, role, model, message):
            return ProviderResult(model, NotificationSummary(summary="ok"),
                                  ModelCapabilities(True, None), None, None)

    budget = TaskBudget(max_calls=2, max_tokens=45)
    router = ModelRouter()
    await invoke_result("notification_summarizer", "inbox", UnknownUsage(), budget=budget,
                        router=router, estimated_tokens=40)
    assert budget.tokens_used == 40
    with pytest.raises(BudgetExhausted):
        await invoke_result("notification_summarizer", "inbox", UnknownUsage(),
                            budget=budget, router=router, estimated_tokens=40)
    assert budget.calls_used == 1
    assert TaskBudget.from_snapshot(budget.snapshot()).tokens_used == 40


@pytest.mark.asyncio
async def test_fallback_records_failure_and_success(monkeypatch):
    router = models(monkeypatch)
    backend = ScriptedBackend([RuntimeError("unavailable"), "recovered"])
    budget = TaskBudget(3, 100)
    attempts = []
    result = await invoke_result("notification_summarizer", "inbox", backend,
                                 budget=budget, router=router, estimated_tokens=20,
                                 observer=attempts.append)
    assert result.attempted_models == ("cheap", "strong")
    assert [attempt.success for attempt in attempts] == [False, True]
    assert attempts[0].error_type == "RuntimeError"
    assert router.records["cheap"].failed_calls == 1
    assert budget.calls_used == 2


@pytest.mark.asyncio
async def test_transient_failure_retries_once_then_falls_back(monkeypatch):
    router = models(monkeypatch)
    backend = ScriptedBackend([TimeoutError(), TimeoutError(), "ok"])
    result = await invoke_result("notification_summarizer", "inbox", backend,
                                 router=router, budget=TaskBudget(3, 100), estimated_tokens=20)
    assert result.attempted_models == ("cheap", "cheap", "strong")


@pytest.mark.asyncio
async def test_rate_limit_cools_model_and_falls_back(monkeypatch):
    router = models(monkeypatch)

    class RateLimitError(Exception):
        status_code = 429

    backend = ScriptedBackend([RateLimitError(), "ok"])
    result = await invoke_result("notification_summarizer", "inbox", backend,
                                 router=router, estimated_tokens=20)
    assert result.model == "strong"
    assert router.records["cheap"].cooldown_until > 0
    assert router.candidates(["cheap", "strong"])[0].name == "strong"


def test_router_filters_quota_context_and_capabilities(monkeypatch):
    router = models(monkeypatch)
    router.records["cheap"].quota_remaining = 0
    assert [m.name for m in router.candidates(["cheap", "strong"])] == ["strong"]
    router.records["strong"].supports_tools = False
    assert router.candidates(["cheap", "strong"], require_tools=True) == []
    router.records["strong"].supports_tools = True
    assert router.candidates(["cheap", "strong"], required_context_tokens=2000)[0].name == "strong"


@pytest.mark.asyncio
async def test_no_available_model_is_explicit(monkeypatch):
    router = models(monkeypatch)
    router.records["cheap"].quota_remaining = 0
    router.records["strong"].quota_remaining = 0
    with pytest.raises(ProviderCallError, match="No model"):
        await invoke_result("notification_summarizer", "inbox", ScriptedBackend([]),
                            router=router, estimated_tokens=20)


def test_router_cooldown_survives_snapshot(monkeypatch):
    router = models(monkeypatch)
    router.failure("cheap", rate_limited=True)
    restored = ModelRouter.from_snapshot(router.snapshot())
    assert [record.name for record in restored.candidates(["cheap", "strong"])] == ["strong"]
    assert restored.records["cheap"].failed_calls == 1


@pytest.mark.asyncio
async def test_observer_failure_never_repeats_successful_call(monkeypatch):
    router = models(monkeypatch)
    backend = ScriptedBackend(["ok"])

    def broken_observer(attempt):
        raise OSError("telemetry store unavailable")

    result = await invoke_result("notification_summarizer", "inbox", backend,
                                 router=router, observer=broken_observer,
                                 estimated_tokens=20)
    assert result.response.summary == "ok"
    assert backend.models == ["cheap"]
