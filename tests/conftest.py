"""Shared test isolation for credential-free planner behavior."""

import pytest


@pytest.fixture(autouse=True)
def disable_live_planner(monkeypatch):
    """Never call a live planner model from the automated suite.

    Planner tests explicitly switch ORIN_PLANNER back to auto and patch the
    provider boundary.
    """
    monkeypatch.setenv("ORIN_PLANNER", "off")
