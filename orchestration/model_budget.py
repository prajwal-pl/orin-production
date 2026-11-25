"""Small, inspectable model registry and per-task inference budget."""

from dataclasses import asdict, dataclass
from time import time
from typing import Literal


Complexity = Literal["simple", "moderate", "complex"]
COMPLEXITY_LEVEL = {"simple": 1, "moderate": 2, "complex": 3}


class BudgetExhausted(RuntimeError):
    """The task cannot safely make another inference call."""


@dataclass
class ModelRecord:
    name: str
    context_window: int | None = None
    supports_structured_output: bool | None = None
    supports_tools: bool | None = None
    supports_json_mode: bool | None = None
    quota_remaining: int | None = None  # Calls remaining, if the provider reports it.
    cooldown_until: float = 0.0  # Unix timestamp so cooldown survives restart.
    complexity_level: int = 1
    successful_calls: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def provider(self) -> str:
        return self.name.split(":", 1)[0]


@dataclass
class TaskBudget:
    max_calls: int
    max_tokens: int
    calls_used: int = 0
    tokens_used: int = 0

    def reserve(self, estimated_tokens: int) -> None:
        if estimated_tokens < 1:
            raise ValueError("Token estimate must be positive")
        if self.calls_used >= self.max_calls or self.tokens_used + estimated_tokens > self.max_tokens:
            raise BudgetExhausted("Task inference budget exhausted")
        self.calls_used += 1
        self.tokens_used += estimated_tokens

    def settle(self, reserved_tokens: int, observed_tokens: int | None) -> None:
        # Missing provider usage retains the conservative reservation.
        if observed_tokens is not None:
            self.tokens_used += observed_tokens - reserved_tokens

    def snapshot(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, int]) -> "TaskBudget":
        return cls(**snapshot)


class ModelRouter:
    def __init__(self, records: list[ModelRecord] | None = None, cooldown_seconds: int = 60):
        self.records = {record.name: record for record in records or []}
        self.cooldown_seconds = cooldown_seconds

    def candidates(
        self,
        models: list[str],
        complexity: Complexity = "simple",
        required_context_tokens: int = 0,
        require_tools: bool = False,
        require_json_mode: bool = False,
    ) -> list[ModelRecord]:
        now = time()
        eligible = []
        for index, name in enumerate(models):
            record = self.records.setdefault(name, ModelRecord(name))
            if (record.quota_remaining is not None and record.quota_remaining <= 0) or record.cooldown_until > now:
                continue
            if record.context_window is not None and record.context_window < required_context_tokens:
                continue
            if record.supports_structured_output is False:
                continue
            if require_tools and record.supports_tools is False:
                continue
            if require_json_mode and record.supports_json_mode is False:
                continue
            eligible.append((index, record))
        if complexity == "simple":
            eligible.sort(key=lambda item: (item[1].complexity_level, item[0]))
        elif complexity == "complex":
            eligible.sort(key=lambda item: (-item[1].complexity_level, item[0]))
        else:
            eligible.sort(key=lambda item: (abs(item[1].complexity_level - 2), item[0]))
        return [record for _, record in eligible]

    def snapshot(self) -> dict:
        return {
            "cooldown_seconds": self.cooldown_seconds,
            "records": [asdict(record) for record in self.records.values()],
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict) -> "ModelRouter":
        return cls([ModelRecord(**record) for record in snapshot["records"]],
                   cooldown_seconds=snapshot["cooldown_seconds"])

    def success(self, model: str, input_tokens: int | None, output_tokens: int | None) -> None:
        record = self.records[model]
        record.successful_calls += 1
        record.supports_structured_output = True
        record.input_tokens += input_tokens or 0
        record.output_tokens += output_tokens or 0
        if record.quota_remaining is not None:
            record.quota_remaining = max(0, record.quota_remaining - 1)
        record.cooldown_until = 0.0

    def failure(self, model: str, *, rate_limited: bool = False) -> None:
        record = self.records[model]
        record.failed_calls += 1
        if rate_limited:
            record.cooldown_until = time() + self.cooldown_seconds
            if record.quota_remaining is not None:
                record.quota_remaining = max(0, record.quota_remaining - 1)
