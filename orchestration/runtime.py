"""Shared durable task entry point for Telegram, CLI, and API."""

import logging
import os
import json
from dataclasses import asdict
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
from orchestration.integrations import authorize_source, connected_sources, fetch_source, SOURCES, summarize_evidence

logger = logging.getLogger(__name__)


class NotificationState(TypedDict):
    task_id: str
    request: str
    notifications: list[dict]
    observations: list[dict]
    source_status: dict[str, str]
    artifact_path: str
    context_excerpt: str
    final_response: str


def task_kind(request: str) -> str:
    lower = request.lower()
    if "briefing" in lower:
        return "daily_briefing"
    if "github" in lower and "notification" in lower:
        return "github_notifications"
    if "gmail" in lower and any(word in lower for word in ("inbox", "unread", "messages")):
        return "gmail_inbox"
    if "drive" in lower and any(word in lower for word in ("files", "documents", "recent")):
        return "drive_recent"
    if "calendar" in lower and any(word in lower for word in ("events", "schedule", "upcoming", "today")):
        return "calendar_upcoming"
    return "prototype"


READ_KINDS = {"github_notifications", "gmail_inbox", "drive_recent", "calendar_upcoming", "daily_briefing"}
KIND_SOURCE = {"github_notifications": "github", "gmail_inbox": "gmail",
               "drive_recent": "drive", "calendar_upcoming": "calendar"}


def _github_evidence(items: list[dict]) -> list[dict]:
    return [{"source": "github", "source_id": item["url"], "title": item["title"],
             "detail": f"{item['repository']} ({item['reason']})", "url": item["url"],
             "occurred_at": ""} for item in items]


def task_reply(task: dict) -> str:
    if task.get("result"):
        return task["result"]
    if task["status"] == "paused" and task.get("error") == "BudgetExhausted":
        return f"Task {task['id']} is paused because its model budget is exhausted. Increase the budget before resuming."
    if task["status"] == "paused" and task.get("error") == "ProviderCallError":
        return f"Task {task['id']} is paused because no model is available. Resume later."
    if task["status"] == "paused" and task.get("error") == "MissingCredential":
        return f"Task {task['id']} is paused because its source is not connected. Configure read-only access, then resume."
    return f"Task {task['id']} is {task['status']}."


class Runtime:
    def __init__(self, path: Path | None = None):
        self.store = TaskStore(path)
        self.memory = MemoryStore(self.store)
        self.skills = SkillRegistry(self.store)
        self.router = ModelRouter([
            ModelRecord(**record) for record in self.store.load_model_records()
        ])
        for name in configured_models():
            record = self.router.records.setdefault(name, ModelRecord(name))
            self.store.save_model_record(asdict(record))

    async def submit(self, owner: str, session_id: str, request: str,
                     idempotency_key: str | None = None) -> dict:
        kind = task_kind(request)
        if kind in KIND_SOURCE:
            authorize_source(owner, KIND_SOURCE[kind])
        return self.store.create_task(owner, session_id, request, kind, idempotency_key)

    async def run(self, owner: str, task_id: str) -> dict:
        task = self.store.get_task(task_id, owner)
        if task is None:
            raise KeyError("Task not found")
        if task["kind"] in KIND_SOURCE:
            authorize_source(owner, KIND_SOURCE[task["kind"]])
        if task["status"] in ("completed", "cancelled"):
            return task
        if task["status"] == "running" and task["worker_pid"]:
            try:
                os.kill(task["worker_pid"], 0)
            except ProcessLookupError:
                self.store.transition(task_id, owner, ("running",), "paused")
            except PermissionError:
                pass
        saved_budget = json.loads(task["budget_state"] or "null")
        budget = TaskBudget.from_snapshot(saved_budget) if saved_budget else TaskBudget(
            max_calls=int(os.getenv("ORIN_TASK_MODEL_CALLS", "3")),
            max_tokens=int(os.getenv("ORIN_TASK_MODEL_TOKENS", "6000")),
        )
        budget.max_calls = max(budget.max_calls, int(os.getenv("ORIN_TASK_MODEL_CALLS", "3")))
        budget.max_tokens = max(budget.max_tokens, int(os.getenv("ORIN_TASK_MODEL_TOKENS", "6000")))
        if not self.store.transition(task_id, owner, ("pending", "paused"), "running"):
            return self.store.get_task(task_id, owner)
        self.store.save_budget_state(task_id, owner, budget.snapshot())

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
                        if kind == "github_notifications":
                            try:
                                items = await fetch_notifications()
                            except Exception:
                                self.store.record_execution(task_id, GITHUB_NOTIFICATIONS.name, "failed")
                                raise
                            self.store.record_execution(task_id, GITHUB_NOTIFICATIONS.name, "completed")
                            statuses["github"] = "completed"
                        elif kind == "daily_briefing":
                            items = []
                            enabled = set(connected_sources(owner))
                            for source, spec in SOURCES.items():
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
                        else:
                            source = KIND_SOURCE[kind]
                            try:
                                items = await fetch_source(source, owner)
                            except Exception:
                                self.store.record_execution(task_id, SOURCES[source].capability, "failed")
                                raise
                            self.store.record_execution(task_id, SOURCES[source].capability, "completed")
                            statuses[source] = "completed"
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
                        }

                    async def summarize(state: NotificationState):
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
                                     "final_response": ""}
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
        except Exception as error:
            logger.error("Task setup failed", extra={"task_id": task_id})
            self.store.transition(task_id, owner, ("running",), "paused", error=type(error).__name__)
        return self.store.get_task(task_id, owner)

    def cancel(self, owner: str, task_id: str) -> dict:
        task = self.store.get_task(task_id, owner)
        if task is None:
            raise KeyError("Task not found")
        self.store.transition(task_id, owner, ("pending", "paused"), "cancelled")
        return self.store.get_task(task_id, owner)
