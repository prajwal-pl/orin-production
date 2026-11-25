# GitHub notification evaluation

The versioned `fixtures/v1.json` contains six synthetic cases. They cover an empty inbox, priority reasons, multiple repositories, duplicate notifications, malformed model output, and a rate limit. The fixtures contain no account data or credentials.

Run the benchmark with `uv run python -m evaluation.benchmark`. It compares a scripted single-model strategy, a scripted budget-aware strategy, and the production deterministic summary function on identical fixture inputs. The budget-aware strategy uses the deterministic function for an empty inbox. Its other cases call Orin's production `invoke_result` routing and `TaskBudget` logic through a scripted backend. The backend returns the same deterministic summary, so the comparison isolates routing behavior. It injects malformed output and a rate limit for the budget-aware primary model. The duplicate case checks that the summary contains each notification once.

The report includes per-case correctness, model choice, call count, token count, measured local wall-clock latency, and fallback recovery. Scripted token counts and delays are test inputs. They do not measure provider usage or provider latency. The deterministic baseline uses zero model calls and zero model tokens. Local latency varies by machine.

The benchmark can accept other async strategies through `compare_strategies`. Live inference comparisons should use the same fixtures, record model IDs and settings, and report observed provider usage separately from this simulation.

## Reproduce the workflow demo

1. Run `uv run python -m pytest tests/test_phase1.py::test_github_checkpoint_resume_skips_completed_fetch -q` to simulate a process interruption after fetching. The test starts a new runtime and confirms that the fetch is reused.
2. Run `uv run python -m pytest tests/test_phase2_integration.py::test_rate_limit_switches_model_and_records_both_attempts -q` to inject a rate limit and confirm the backup model completes the task. The test checks both usage records and the user-facing fallback message.
3. Run `uv run python -m evaluation.benchmark` for the six-case comparison. Inspect `task_success_rate`, `total_tokens`, `mean_latency_ms`, and `fallback_recoveries` in its JSON report.
4. With local credentials configured as described in the root README, run `uv run python -m orchestration.cli "Summarize my GitHub notifications"`, then send the same request to the Telegram bot. These calls use the live GitHub account and may return private notification titles, so keep the output local.

On 2026-11-25, the six synthetic cases passed for each scripted strategy. The scripted single-model run used 600 fixture tokens over six calls. The budget-aware run used 360 fixture tokens over seven calls and recovered from two injected primary-model failures. A separate live smoke check ran a synthetic five-notification task through OpenRouter and a structured classifier call through local Ollama. These live checks confirm connectivity and structured responses; their account data and token values are excluded from the fixtures.

## Phase 3 learning demo

Run `uv run python -m evaluation.learning`. It creates a temporary SQLite
profile and a synthetic crowded GitHub inbox. Ten review requests precede a
security alert. The built-in ordering passes six of seven checks because the
alert falls outside the ten displayed items. A successful task proposes a
declarative priority skill; its fixture validation passes seven of seven.
After explicit activation, the same workflow displays the alert. Re-activating
the built-in version restores the original output. The report includes actual
task completion, per-version task counts, model calls, user corrections, and
three simple memory top-one retrieval checks. All runs use the local summary
with zero model calls and synthetic inputs. Memory vectors use character
n-grams, so the retrieval checks measure fuzzy lexical relevance, not neural
semantic quality. The test suite also checks owner isolation, memory deletion
from indexes, skill permission constraints, and migration from schema v6.

## Cross-source read demo

Run `uv run python -m pytest tests/test_integrations.py -q`. The suite mocks
Google HTTP responses while exercising the actual read-only Gmail header,
Drive metadata, and Calendar event requests. It then runs a synthetic daily
briefing through the shared LangGraph task runtime, records an episode and
skill version, proposes “calendar first” from user feedback, activates it,
and verifies rollback. A separate test passes Gmail provider HTTP responses
through the full runtime and checks its private artifact. This does not use a
live Google account. `INTEGRATIONS.md` documents the required scopes and OAuth
work before live Google use.
