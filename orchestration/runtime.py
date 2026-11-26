"""Shared durable task entry point for Telegram, CLI, and API."""

import asyncio
import logging
import os
import json
import re
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph, START, END

from orchestration.github import fetch_notifications, summarize_notifications, GITHUB_NOTIFICATIONS
from orchestration.context import ArtifactStore, ContextItem, build_context
from orchestration.agents import configured_models, inference_options, invoke_result
from orchestration.model_budget import BudgetExhausted, ModelRecord, ModelRouter, TaskBudget
from orchestration.graph import builder as prototype_builder
from orchestration.store import TaskStore
from orchestration.memory import MemoryStore
from orchestration.skills import SkillRegistry
from orchestration.skills import BRIEFING_NAME
from orchestration.integrations import (authorize_source, connected_sources, fetch_source,
                                        fetch_gmail_request, plan_gmail_request, SOURCES, summarize_evidence)
from orchestration.policy import PolicyStore
from orchestration.actions import ActionStore
from orchestration.scheduler import ScheduledJobStore
from orchestration.delegation import DelegationStore, Delegator
from orchestration.sync import SyncStore, SyncEngine
from orchestration.search import SearchIndex
from orchestration.productivity import prepare_meeting, follow_up_queue
from orchestration.mcp_registry import MCPRegistry

logger = logging.getLogger(__name__)

# Task IDs currently executing in this process. A cancelled request can leave a
# worker PID recorded while no coroutine is running; this set distinguishes a
# live run from a stale claim without adding a background heartbeat.
_ACTIVE_RUNS: set[str] = set()
_ACTIVE_RUNS_LOCK = threading.Lock()


def _run_active(task_id: str) -> bool:
    with _ACTIVE_RUNS_LOCK:
        return task_id in _ACTIVE_RUNS


def _mark_run(task_id: str, active: bool) -> None:
    with _ACTIVE_RUNS_LOCK:
        if active:
            _ACTIVE_RUNS.add(task_id)
        else:
            _ACTIVE_RUNS.discard(task_id)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class NotificationState(TypedDict):
    task_id: str
    request: str
    notifications: list[dict]
    observations: list[dict]
    source_status: dict[str, str]
    artifact_path: str
    context_excerpt: str
    final_response: str
    gmail_response: str


def task_kind(request: str) -> str:
    lower = request.lower()
    if any(phrase in lower for phrase in ("meeting prep", "prepare for my meeting", "prepare me for")):
        return "meeting_prep"
    if any(phrase in lower for phrase in ("follow-up", "follow up", "followup queue")):
        return "follow_up"
    if "briefing" in lower:
        return "daily_briefing"
    if "github" in lower and "notification" in lower:
        return "github_notifications"
    if (re.search(r"\b(?:gmail|e-?mails?|inbox)\b", lower)
            and re.search(r"\b(?:check|show|list|read|find|last|latest|recent|unread|inbox)\b", lower)
            and not re.search(r"\b(?:send|draft|reply|forward|delete|archive|mark|label)\b", lower)):
        return "gmail_inbox"
    if "drive" in lower and any(word in lower for word in ("files", "documents", "recent")):
        return "drive_recent"
    if "calendar" in lower and any(word in lower for word in ("events", "schedule", "upcoming", "today")):
        return "calendar_upcoming"
    for source in ("notion", "todoist", "slack", "microsoft"):
        if source in lower:
            return f"{source}_recent"
    return "prototype"


READ_KINDS = {"github_notifications", "gmail_inbox", "drive_recent", "calendar_upcoming",
              "daily_briefing", "meeting_prep", "follow_up",
              "notion_recent", "todoist_recent", "slack_recent", "microsoft_recent"}
KIND_SOURCE = {"github_notifications": "github", "gmail_inbox": "gmail",
               "drive_recent": "drive", "calendar_upcoming": "calendar",
               "notion_recent": "notion", "todoist_recent": "todoist",
               "slack_recent": "slack", "microsoft_recent": "microsoft"}


def _github_evidence(items: list[dict]) -> list[dict]:
    return [{"source": "github", "source_id": item["url"], "title": item["title"],
             "detail": f"{item['repository']} ({item['reason']})", "url": item["url"],
             "occurred_at": ""} for item in items]


def _annotate_evidence(items: list[dict], owner: str) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    annotated = []
    for item in items:
        record = dict(item)
        source = record.get("source", "")
        record.setdefault("account_id", os.getenv(f"ORIN_{source.upper()}_ACCOUNT_ID", "unverified"))
        record.setdefault("fetched_at", now)
        record.setdefault("content_kind", "content" if source in {"slack", "todoist"} else "metadata")
        record["owner"] = owner
        annotated.append(record)
    return annotated


def _meeting_summary(owner: str, request: str, items: list[dict]) -> str:
    events = [item for item in items if item["source"] == "calendar"]
    if not events:
        return "No upcoming Calendar event was available for meeting preparation."
    terms = set(re.findall(r"[a-z0-9]{3,}", request.lower())) - {
        "prepare", "meeting", "today", "tomorrow", "please", "my", "for"}
    event = max(events, key=lambda item: len(terms & set(re.findall(r"[a-z0-9]{3,}", item["title"].lower()))))
    prepared = prepare_meeting(owner, event, items)
    lines = [f"Meeting preparation: {prepared['meeting']['title']}",
             f"Event: {prepared['meeting']['url']}"]
    for item in prepared["related"]:
        lines.append(f"- [{item['source']}] {item['title']} {item['url']}")
    for question in prepared["open_questions"]:
        lines.append(f"Open question: {question}")
    lines.append(prepared["note"])
    return "\n".join(lines)


def _follow_up_summary(owner: str, items: list[dict]) -> str:
    queue = follow_up_queue(owner, items)
    lines = [f"Possible follow-ups to review: {len(queue)}"]
    for candidate in queue:
        item = candidate["evidence"]
        lines.append(f"- [{item['source']}] {item['title']} — {candidate['reason']} {item['url']}")
    return "\n".join(lines)


def task_reply(task: dict) -> str:
    if task.get("result"):
        return task["result"]
    if task["status"] == "paused" and task.get("error") in {"Cancelled", "Interrupted"}:
        return (f"Task {task['id']} was interrupted before it finished. "
                f"Resume it with /resume {task['id']} or from the control center.")
    if task["status"] == "paused" and task.get("error") == "BudgetExhausted":
        return f"Task {task['id']} is paused because its model budget is exhausted. Increase the budget before resuming."
    if task["status"] == "paused" and task.get("error") == "ProviderCallError":
        return f"Task {task['id']} is paused because no model is available. Resume later."
    if task["status"] == "paused" and task.get("error") == "MissingCredential":
        return f"Task {task['id']} is paused because its source is not connected. Configure read-only access, then resume."
    return f"Task {task['id']} is {task['status']}."


class Runtime:
    _active_delegations: dict[str, object] = {}

    def __init__(self, path: Path | None = None):
        self.store = TaskStore(path)
        base = self.store.path
        self.policy = PolicyStore(base.with_name(base.stem + "-policy.db"))
        self.mcp = MCPRegistry(self.policy)
        self.actions = ActionStore(base.with_name(base.stem + "-actions.db"), self.policy)
        self.schedules = ScheduledJobStore(base.with_name(base.stem + "-schedules.db"))
        self.delegations = DelegationStore(base)
        self.sync_store = SyncStore(base.with_name(base.stem + "-sync.db"))
        self.sync_engine = SyncEngine(self.sync_store)
        self.search = SearchIndex(self.sync_store)
        self.memory = MemoryStore(self.store)
        self.skills = SkillRegistry(self.store)
        self.router = ModelRouter([
            ModelRecord(**record) for record in self.store.load_model_records()
        ])
        for name in configured_models():
            if name not in self.router.records:
                record = ModelRecord(name)
                self.router.records[name] = record
                self.store.save_model_record(asdict(record))

    async def submit(self, owner: str, session_id: str, request: str,
                     idempotency_key: str | None = None) -> dict:
        kind = task_kind(request)
        if kind in KIND_SOURCE:
            authorize_source(owner, KIND_SOURCE[kind])
        if idempotency_key and idempotency_key.startswith("delegate:"):
            delegation = self.delegations.get(owner, idempotency_key.removeprefix("delegate:"))
            if not delegation or delegation["request"] != request or delegation["session_id"] != session_id:
                raise PermissionError("Delegation identity does not match child task")
            self._check_delegated_kind(owner, kind, set(delegation["allowed_capabilities"]))
        return self.store.create_task(owner, session_id, request, kind, idempotency_key)

    @staticmethod
    def _required_capabilities(owner: str, kind: str) -> set[str]:
        if kind in KIND_SOURCE:
            return {SOURCES[KIND_SOURCE[kind]].capability}
        if kind in {"daily_briefing", "meeting_prep", "follow_up"}:
            keys = connected_sources(owner)
            if kind in {"meeting_prep", "follow_up"}:
                keys = [key for key in keys if key not in {"slack", "todoist"}]
            return {SOURCES[key].capability for key in keys}
        return {"prototype.mock"}

    def _check_delegated_kind(self, owner: str, kind: str, allowed: set[str]) -> None:
        if not self._required_capabilities(owner, kind) <= allowed:
            raise PermissionError("Delegated task exceeds its allowed capabilities")

    def _delegation_for_task(self, owner: str, task: dict) -> dict | None:
        key = task.get("idempotency_key") or ""
        if not key.startswith("delegate:"):
            return None
        item = self.delegations.get(owner, key.removeprefix("delegate:"))
        if not item or item["request"] != task["request"]:
            raise PermissionError("Delegation record is missing or mismatched")
        if item["status"] == "cancelled":
            raise PermissionError("Delegated task was cancelled")
        self._check_delegated_kind(owner, task["kind"], set(item["allowed_capabilities"]))
        return item

    async def run(self, owner: str, task_id: str,
                  max_model_calls: int | None = None, max_model_tokens: int | None = None) -> dict:
        task = self.store.get_task(task_id, owner)
        if task is None:
            raise KeyError("Task not found")
        if task["kind"] in KIND_SOURCE:
            authorize_source(owner, KIND_SOURCE[task["kind"]])
        delegated = self._delegation_for_task(owner, task)
        if delegated:
            max_model_calls = delegated["max_model_calls"]
            max_model_tokens = delegated["max_model_tokens"]
        elif max_model_calls is not None or max_model_tokens is not None:
            raise PermissionError("Task budget overrides require a delegated task")
        if task["status"] in ("completed", "cancelled"):
            return task
        if task["status"] == "running":
            pid = task.get("worker_pid")
            if pid is None or pid <= 0:
                self.store.transition(task_id, owner, ("running",), "paused",
                                      error="Interrupted")
            elif pid != os.getpid():
                if _pid_alive(pid):
                    # Another worker process owns this run. Do not steal it.
                    return task
                self.store.transition(task_id, owner, ("running",), "paused",
                                      error="Interrupted")
            elif _run_active(task_id):
                # This process is already executing the task in another coroutine.
                return task
            else:
                # The worker PID is ours, but no coroutine is running the task:
                # the request was cancelled or the event loop stopped it.
                self.store.transition(task_id, owner, ("running",), "paused",
                                      error="Interrupted")
            task = self.store.get_task(task_id, owner)
        saved_budget = json.loads(task["budget_state"] or "null")
        budget = TaskBudget.from_snapshot(saved_budget) if saved_budget else TaskBudget(
            max_calls=max_model_calls if delegated else int(os.getenv("ORIN_TASK_MODEL_CALLS", "3")),
            max_tokens=max_model_tokens if delegated else int(os.getenv("ORIN_TASK_MODEL_TOKENS", "6000")),
        )
        if delegated:
            budget.max_calls = min(budget.max_calls, max_model_calls)
            budget.max_tokens = min(budget.max_tokens, max_model_tokens)
        else:
            budget.max_calls = max(budget.max_calls, int(os.getenv("ORIN_TASK_MODEL_CALLS", "3")))
            budget.max_tokens = max(budget.max_tokens, int(os.getenv("ORIN_TASK_MODEL_TOKENS", "6000")))
        if not self.store.transition(task_id, owner, ("pending", "paused"), "running"):
            return self.store.get_task(task_id, owner)
        self.store.save_budget_state(task_id, owner, budget.snapshot())
        _mark_run(task_id, True)

        def observe(attempt):
            self.store.record_model_call(
                task_id, attempt.model, attempt.role, attempt.input_tokens,
                attempt.output_tokens, attempt.latency_ms, attempt.success,
            )
            self.store.save_budget_state(task_id, owner, budget.snapshot())
            self.store.save_model_record(asdict(self.router.records[attempt.model]))

        try:
            checkpoint_path = self.store.path.with_name(self.store.path.stem + "-checkpoints.db")
            descriptor = os.open(checkpoint_path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
            async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                await saver.setup()
                config = {"configurable": {"thread_id": task_id}}
                if task["kind"] in READ_KINDS:
                    async def fetch(state: NotificationState):
                        self.store.record_step(task_id, "fetch", "started")
                        kind = task["kind"]
                        statuses: dict[str, str] = {}
                        gmail_summary = ""
                        if kind == "github_notifications":
                            try:
                                items = await fetch_notifications()
                            except Exception:
                                self.store.record_execution(task_id, GITHUB_NOTIFICATIONS.name, "failed")
                                raise
                            self.store.record_execution(task_id, GITHUB_NOTIFICATIONS.name, "completed")
                            statuses["github"] = "completed"
                        elif kind in {"daily_briefing", "meeting_prep", "follow_up"}:
                            items = []
                            enabled = set(connected_sources(owner))
                            for source, spec in SOURCES.items():
                                if kind in {"meeting_prep", "follow_up"} and source in {"slack", "todoist"}:
                                    continue  # The productivity procedures are metadata-only.
                                if source not in enabled:
                                    statuses[source] = "not connected"
                                    continue
                                try:
                                    fetched = (_github_evidence(await fetch_notifications()) if source == "github"
                                               else await fetch_source(source, owner))
                                except Exception:
                                    self.store.record_execution(task_id, spec.capability, "failed")
                                    statuses[source] = "unavailable"
                                    continue
                                items.extend(fetched)
                                statuses[source] = "completed"
                                self.store.record_execution(task_id, spec.capability, "completed")
                        elif kind == "gmail_inbox" and (plan := plan_gmail_request(task["request"])):
                            try:
                                read = await fetch_gmail_request(owner, plan)
                                items = read.items
                                gmail_summary = read.summary
                            except Exception:
                                self.store.record_execution(task_id, SOURCES["gmail"].capability, "failed")
                                raise
                            self.store.record_execution(task_id, SOURCES["gmail"].capability, "completed")
                            statuses["gmail"] = "completed"
                        else:
                            source = KIND_SOURCE[kind]
                            try:
                                items = await fetch_source(source, owner)
                            except Exception:
                                self.store.record_execution(task_id, SOURCES[source].capability, "failed")
                                raise
                            self.store.record_execution(task_id, SOURCES[source].capability, "completed")
                            statuses[source] = "completed"
                        if kind != "github_notifications":
                            items = _annotate_evidence(items, owner)
                            try:
                                self.search.ingest_evidence(owner, items)
                            except ValueError:
                                logger.error("Read evidence could not be indexed", extra={"task_id": task_id})
                        self.store.record_step(task_id, "fetch", "completed")
                        observation = ArtifactStore(self.store.path.parent / "artifacts").save(
                            task_id, kind, json.dumps(items, ensure_ascii=False)
                        )
                        self.store.record_artifact(task_id, str(observation.artifact_path), observation.byte_count)
                        return {
                            "notifications": items if kind == "github_notifications" else [],
                            "observations": items if kind != "github_notifications" else [],
                            "source_status": statuses,
                            "artifact_path": str(observation.artifact_path),
                            "context_excerpt": observation.context_text(),
                            "gmail_response": gmail_summary,
                        }

                    async def summarize(state: NotificationState):
                        if state.get("gmail_response"):
                            self.store.record_step(task_id, "summarize_local", "completed")
                            return {"final_response": state["gmail_response"]}
                        if task["kind"] == "meeting_prep":
                            return {"final_response": _meeting_summary(owner, task["request"], state["observations"])}
                        if task["kind"] == "follow_up":
                            return {"final_response": _follow_up_summary(owner, state["observations"])}
                        github = task["kind"] == "github_notifications"
                        items = state["notifications"] if github else state["observations"]
                        skill = self.skills.active(owner, name="github_notifications_priority" if github else BRIEFING_NAME)
                        self.skills.record_use(task_id, skill["id"])
                        procedure = json.loads(skill["procedure"])
                        if github:
                            priority_reasons = procedure["priority_reasons"] or None
                            local_summary = (summarize_notifications(items, priority_reasons)
                                             if priority_reasons else summarize_notifications(items))
                        else:
                            local_summary = summarize_evidence(items, state["source_status"], procedure["source_order"])
                        if len(items) < 5:
                            self.store.record_step(task_id, "summarize_local", "completed")
                            return {"final_response": local_summary}

                        try:
                            sources = [ContextItem("working", state["context_excerpt"], 1.0)]
                            sources.extend(
                                ContextItem("persistent", message, 0.4)
                                for message in self.store.relevant_messages(owner, task["request"])
                            )
                            sources.extend(
                                ContextItem("persistent", memory["content"], 0.7)
                                for memory in self.memory.search(owner, task["request"], limit=3)
                            )
                            sources.append(ContextItem("procedural", skill["content"], 0.6))
                            context = build_context(
                                task["request"], f"Fetched {len(items)} read-only source items.",
                                sources,
                                max_tokens=int(os.getenv("ORIN_CONTEXT_TOKENS", "4096")),
                                reserve_tokens=int(os.getenv("ORIN_OUTPUT_RESERVE", "512")),
                            )
                            complexity = "complex" if len(items) >= 20 else "moderate"
                            result = await invoke_result(
                                "notification_summarizer" if github else "read_summarizer", context.text,
                                budget=budget, router=self.router, complexity=complexity,
                                estimated_tokens=context.input_tokens + context.output_reserve,
                                observer=observe,
                            )
                            self.store.save_budget_state(task_id, owner, budget.snapshot())
                            highlights = result.response.summary.strip()[:1200]
                            if len(set(result.attempted_models)) > 1:
                                self.store.record_step(task_id, "model_fallback", "completed")
                                model_status = "Model fallback used.\n"
                            else:
                                model_status = ""
                            reply = f"{model_status}Suggested focus: {highlights}\n\n{local_summary}" if highlights else local_summary
                        except (BudgetExhausted, ValueError, RuntimeError):
                            self.store.record_step(task_id, "local_summary_fallback", "completed")
                            reply = "Model analysis was unavailable within the task budget. Local summary follows.\n\n" + local_summary
                        self.store.record_step(task_id, "summarize", "completed")
                        return {"final_response": reply}

                    builder = StateGraph(NotificationState)
                    builder.add_node("fetch", fetch)
                    builder.add_node("summarize", summarize)
                    builder.add_edge(START, "fetch")
                    builder.add_edge("fetch", "summarize")
                    builder.add_edge("summarize", END)
                    graph = builder.compile(checkpointer=saver)
                    initial_state = {"task_id": task_id, "request": task["request"],
                                     "notifications": [], "observations": [], "source_status": {},
                                     "artifact_path": "",
                                     "context_excerpt": "",
                                     "final_response": "", "gmail_response": ""}
                else:
                    graph = prototype_builder.compile(checkpointer=saver)
                    initial_state = {
                        "user_id": owner, "message": task["request"], "intent": "",
                        "service": "other", "arguments": {}, "execution_result": {},
                        "execution_status": "pending", "feedback": "",
                        "verification_result": {}, "verification_status": "pending",
                        "retry_count": 0, "final_response": "",
                    }
                try:
                    checkpoint = await saver.aget_tuple(config)
                    with inference_options(budget=budget, router=self.router, observer=observe):
                        result = await graph.ainvoke(None if checkpoint else initial_state, config=config)
                    reply = result["final_response"]
                    self.store.transition(task_id, owner, ("running",), "completed", reply)
                    if task["kind"] in READ_KINDS:
                        try:
                            self.memory.add(owner, "episodic", reply[:8000], f"task:{task_id}")
                            if task["kind"] == "github_notifications":
                                proposal = self.skills.propose_from_task(owner, task_id, result["notifications"])
                                if proposal:
                                    self.store.record_step(task_id, "skill_proposed", "completed")
                        except Exception:
                            logger.exception("Post-task learning failed", extra={"task_id": task_id})
                except Exception as error:
                    logger.error("Task execution paused after failure", extra={"task_id": task_id})
                    self.store.transition(task_id, owner, ("running",), "paused", error=type(error).__name__)
        except asyncio.CancelledError:
            # The client disconnected, the process is shutting down, or a
            # delegation timed out. Release the claim so a later resume can run
            # instead of leaving the task stuck in "running".
            try:
                self.store.transition(task_id, owner, ("running",), "paused",
                                      error="Cancelled")
            except Exception:
                logger.exception("Could not persist cancelled task state",
                                 extra={"task_id": task_id})
            logger.warning("Task run cancelled", extra={"task_id": task_id})
            raise
        except Exception as error:
            logger.error("Task setup failed", extra={"task_id": task_id})
            self.store.transition(task_id, owner, ("running",), "paused", error=type(error).__name__)
        finally:
            _mark_run(task_id, False)
        return self.store.get_task(task_id, owner)

    def cancel(self, owner: str, task_id: str) -> dict:
        task = self.store.get_task(task_id, owner)
        if task is None:
            raise KeyError("Task not found")
        self.store.transition(task_id, owner, ("pending", "paused"), "cancelled")
        for child_id in self.delegations.cancel_parent(owner, task_id):
            self.cancel_delegation(owner, child_id)
        return self.store.get_task(task_id, owner)

    def create_delegation(self, owner: str, parent_task_id: str, request: str,
                          allowed_capabilities: set[str], max_model_calls: int,
                          max_model_tokens: int):
        parent = self.store.get_task(parent_task_id, owner)
        if parent is None:
            raise KeyError("Parent task not found")
        self._check_delegated_kind(owner, task_kind(request), allowed_capabilities)
        parent_budget = json.loads(parent["budget_state"] or "null") or {
            "max_calls": int(os.getenv("ORIN_TASK_MODEL_CALLS", "3")),
            "max_tokens": int(os.getenv("ORIN_TASK_MODEL_TOKENS", "6000")),
            "calls_used": 0, "tokens_used": 0}
        return self.delegations.create(
            owner, parent_task_id, request, allowed_capabilities,
            self._required_capabilities(owner, parent["kind"]),
            max_model_calls=max_model_calls, max_model_tokens=max_model_tokens,
            parent_max_calls=max(0, parent_budget["max_calls"] - parent_budget["calls_used"]),
            parent_max_tokens=max(0, parent_budget["max_tokens"] - parent_budget["tokens_used"]),
        )

    async def run_delegation(self, owner: str, child_id: str) -> dict:
        async def runner(spec):
            task = await self.submit(spec.owner, spec.session_id, spec.request,
                                     idempotency_key=spec.idempotency_key)
            return await self.run(spec.owner, task["id"],
                                  max_model_calls=spec.max_model_calls,
                                  max_model_tokens=spec.max_model_tokens)
        delegator = Delegator(self.delegations, runner)
        current = asyncio.current_task()
        self._active_delegations[child_id] = current
        try:
            return await delegator.execute(owner, child_id)
        finally:
            self._active_delegations.pop(child_id, None)

    def cancel_delegation(self, owner: str, child_id: str) -> dict | None:
        child = self.delegations.cancel(owner, child_id)
        if child is None:
            return None
        active = self._active_delegations.get(child_id)
        if active is not None:
            active.cancel()
        task_id = child.get("child_task_id")
        if task_id:
            self.store.transition(task_id, owner, ("pending", "paused"), "cancelled")
        return child
