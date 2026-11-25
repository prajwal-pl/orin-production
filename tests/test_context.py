from pathlib import Path

import pytest

from orchestration.context import (
    ArtifactStore,
    ContextBudgetError,
    ContextItem,
    build_context,
    count_tokens,
)


def test_provider_tokenizer_and_conservative_estimate():
    assert count_tokens("sample", lambda value: 7) == 7
    assert count_tokens("hello", lambda value: -1) >= 2
    assert count_tokens("你好") >= 2
    assert count_tokens("") == 0


def test_objective_and_state_are_never_truncated():
    sources = [ContextItem("archived", "a" * 200, 0.1)]
    packet = build_context(
        "Finish the user request", "fetch completed", sources,
        max_tokens=80, reserve_tokens=20,
    )
    assert "Finish the user request" in packet.text
    assert "fetch completed" in packet.text
    assert not packet.selected_layers
    assert packet.input_tokens + packet.output_reserve <= 80
    with pytest.raises(ContextBudgetError):
        build_context("objective" * 100, "critical state", (), 20, 10)


def test_selects_relevant_layers_and_only_requested_tools():
    packet = build_context(
        "Summarize notifications", "fetch completed",
        [ContextItem("archived", "old transcript", 0),
         ContextItem("working", "review_requested is important", 0.9),
         ContextItem("persistent", "owner prefers short summaries", 0.7),
         ContextItem("procedural", "format as bullets", 0.6)],
        max_tokens=240, reserve_tokens=40,
        available_tools={"github.read": "Fetch notifications", "gmail.write": "Send mail"},
        needed_tools=["github.read"],
    )
    assert "old transcript" not in packet.text
    assert packet.selected_layers == ("working", "persistent", "procedural")
    assert packet.selected_tools == ("github.read",)
    assert "gmail.write" not in packet.text


def test_raw_output_is_private_and_excerpt_is_redacted(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts", excerpt_chars=80)
    secret = "ghp_" + "A" * 30
    observation = store.save("task-1", "fetch", f"line one\n{secret}\n" + "x" * 100)
    assert secret in observation.artifact_path.read_text()
    assert secret not in observation.context_text()
    assert "[REDACTED]" in observation.excerpt
    assert observation.truncated
    assert observation.byte_count > 100
    assert observation.artifact_path.stat().st_mode & 0o777 == 0o600
    next_observation = store.save("task-1", "fetch", "second result")
    assert next_observation.artifact_path != observation.artifact_path
    assert observation.artifact_path.exists()
    with pytest.raises(ValueError):
        store.save("../escape", "fetch", "bad")


def test_secret_crossing_excerpt_boundary_is_redacted(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts", excerpt_chars=15)
    secret = "ghp_" + "A" * 30
    observation = store.save("task-1", "fetch", "prefix " + secret)
    assert "ghp_" not in observation.excerpt
