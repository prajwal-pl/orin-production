"""Bounded context selection and local tool-output artifacts."""

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence
from uuid import uuid4


ContextLayer = Literal["active", "working", "persistent", "procedural", "archived"]
LAYER_PRIORITY: dict[ContextLayer, int] = {
    "active": 0,
    "working": 1,
    "persistent": 2,
    "procedural": 3,
    "archived": 4,
}
_SECRET_PATTERN = re.compile(
    r"(?i)(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-or-[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._~-]{20,})"
)
_SAFE_NAME = re.compile(r"[A-Za-z0-9_-]+")


def redact_text(content: str) -> str:
    return _SECRET_PATTERN.sub("[REDACTED]", content)


class ContextBudgetError(ValueError):
    """The active objective and execution state exceed the input budget."""


@dataclass(frozen=True)
class ContextItem:
    layer: ContextLayer
    content: str
    relevance: float = 1.0


@dataclass(frozen=True)
class ContextPacket:
    text: str
    selected_layers: tuple[ContextLayer, ...]
    selected_tools: tuple[str, ...]
    input_tokens: int
    output_reserve: int


@dataclass(frozen=True)
class ToolObservation:
    artifact_path: Path
    byte_count: int
    line_count: int
    excerpt: str
    truncated: bool

    def context_text(self) -> str:
        """Structured, bounded data that may be supplied to a model."""
        return json.dumps({
            "artifact": str(self.artifact_path),
            "bytes": self.byte_count,
            "lines": self.line_count,
            "excerpt": self.excerpt,
            "truncated": self.truncated,
        }, ensure_ascii=False)


def count_tokens(text: str, tokenizer: Callable[[str], int] | None = None) -> int:
    """Use a provider counter when available, or estimate conservatively."""
    if not text:
        return 0
    if tokenizer is not None:
        try:
            result = tokenizer(text)
            if isinstance(result, int) and result > 0:
                return result
        except Exception:
            pass
    return max(1, math.ceil(len(text.encode("utf-8")) / 3))


def build_context(
    objective: str,
    execution_state: str,
    sources: Sequence[ContextItem],
    max_tokens: int,
    reserve_tokens: int,
    tokenizer: Callable[[str], int] | None = None,
    available_tools: Mapping[str, str] | None = None,
    needed_tools: Sequence[str] = (),
) -> ContextPacket:
    """Retain critical state and select only relevant material that fits."""
    if max_tokens <= 0 or reserve_tokens < 0 or reserve_tokens >= max_tokens:
        raise ValueError("Invalid context or output reserve budget")
    if not objective.strip():
        raise ValueError("An active objective is required")
    budget = max_tokens - reserve_tokens
    content = f"[active objective]\n{redact_text(objective)}\n[execution state]\n{redact_text(execution_state)}"
    if count_tokens(content, tokenizer) > budget:
        raise ContextBudgetError("Active objective and execution state exceed the input budget")

    selected_layers: list[ContextLayer] = []
    selected_tools: list[str] = []
    candidates = sorted(
        (item for item in sources if item.content.strip() and item.relevance > 0),
        key=lambda item: (-item.relevance, LAYER_PRIORITY[item.layer]),
    )
    for item in candidates:
        excerpt = f"\n[{item.layer} context]\n{redact_text(item.content)}"
        if count_tokens(content + excerpt, tokenizer) <= budget:
            content += excerpt
            selected_layers.append(item.layer)

    available_tools = available_tools or {}
    for name in dict.fromkeys(needed_tools):
        description = available_tools.get(name)
        if not description:
            continue
        excerpt = f"\n[available tool]\n{name}: {redact_text(description)}"
        if count_tokens(content + excerpt, tokenizer) <= budget:
            content += excerpt
            selected_tools.append(name)

    return ContextPacket(
        text=content,
        selected_layers=tuple(selected_layers),
        selected_tools=tuple(selected_tools),
        input_tokens=count_tokens(content, tokenizer),
        output_reserve=reserve_tokens,
    )


class ArtifactStore:
    """Store raw tool output locally and return a bounded observation."""

    def __init__(self, root: Path, excerpt_chars: int = 1200):
        if excerpt_chars < 0:
            raise ValueError("excerpt_chars must be non-negative")
        self.root = Path(root)
        self.excerpt_chars = excerpt_chars
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def save(self, task_id: str, name: str, content: str) -> ToolObservation:
        if not _SAFE_NAME.fullmatch(task_id) or not _SAFE_NAME.fullmatch(name):
            raise ValueError("Task ID and artifact name may contain letters, digits, _ and - only")
        directory = self.root / task_id
        directory.mkdir(mode=0o700, exist_ok=True)
        artifact = directory / f"{name}-{uuid4().hex}.txt"
        raw = content.encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".artifact-", delete=False) as file:
            temporary = Path(file.name)
            os.chmod(temporary, 0o600)
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, artifact)
        redacted = redact_text(content)
        excerpt = redacted[:self.excerpt_chars]
        return ToolObservation(
            artifact_path=artifact,
            byte_count=len(raw),
            line_count=len(content.splitlines()),
            excerpt=excerpt,
            truncated=len(content) > self.excerpt_chars,
        )
