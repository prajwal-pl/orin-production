"""Shared durable task entry point for Telegram, CLI, and API."""

import logging
import os
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph, START, END

from orchestration.github import authorize_notifications, fetch_notifications, summarize_notifications, GITHUB_NOTIFICATIONS
from orchestration.graph import builder as prototype_builder
from orchestration.store import TaskStore

logger = logging.getLogger(__name__)


class NotificationState(TypedDict):
    task_id: str
    request: str
    notifications: list[dict]
    final_response: str


def task_kind(request: str) -> str:
    lower = request.lower()
    return "github_notifications" if "github" in lower and "notification" in lower else "prototype"


class Runtime:
    def __init__(self, path: Path | None = None):
        self.store = TaskStore(path)

    async def submit(self, owner: str, session_id: str, request: str,
                     idempotency_key: str | None = None) -> dict:
        kind = task_kind(request)
        if kind == "github_notifications":
            authorize_notifications(owner)
        return self.store.create_task(owner, session_id, request, kind, idempotency_key)

    async def run(self, owner: str, task_id: str) -> dict:
        task = self.store.get_task(task_id, owner)
        if task is None:
            raise KeyError("Task not found")
        if task["kind"] == "github_notifications":
            authorize_notifications(owner)
        if task["status"] in ("completed", "cancelled"):
            return task
        if task["status"] == "running" and task["worker_pid"]:
            try:
                os.kill(task["worker_pid"], 0)
            except ProcessLookupError:
                self.store.transition(task_id, owner, ("running",), "paused")
            except PermissionError:
                pass
        if not self.store.transition(task_id, owner, ("pending", "paused"), "running"):
            return self.store.get_task(task_id, owner)

        checkpoint_path = self.store.path.with_name(self.store.path.stem + "-checkpoints.db")
        descriptor = os.open(checkpoint_path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            config = {"configurable": {"thread_id": task_id}}
            if task["kind"] == "github_notifications":
                async def fetch(state: NotificationState):
                    self.store.record_step(task_id, "fetch", "started")
                    try:
                        items = await fetch_notifications()
                    except Exception:
                        self.store.record_execution(task_id, GITHUB_NOTIFICATIONS.name, "failed")
                        raise
                    self.store.record_execution(task_id, GITHUB_NOTIFICATIONS.name, "completed")
                    self.store.record_step(task_id, "fetch", "completed")
                    return {"notifications": items}

                async def summarize(state: NotificationState):
                    self.store.record_step(task_id, "summarize", "completed")
                    return {"final_response": summarize_notifications(state["notifications"])}

                builder = StateGraph(NotificationState)
                builder.add_node("fetch", fetch)
                builder.add_node("summarize", summarize)
                builder.add_edge(START, "fetch")
                builder.add_edge("fetch", "summarize")
                builder.add_edge("summarize", END)
                graph = builder.compile(checkpointer=saver)
                initial_state = {"task_id": task_id, "request": task["request"],
                                 "notifications": [], "final_response": ""}
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
                result = await graph.ainvoke(None if checkpoint else initial_state, config=config)
                reply = result["final_response"]
                self.store.transition(task_id, owner, ("running",), "completed", reply)
            except Exception as error:
                logger.error("Task execution paused after failure", extra={"task_id": task_id})
                self.store.transition(task_id, owner, ("running",), "paused", error=type(error).__name__)
        return self.store.get_task(task_id, owner)

    def cancel(self, owner: str, task_id: str) -> dict:
        task = self.store.get_task(task_id, owner)
        if task is None:
            raise KeyError("Task not found")
        self.store.transition(task_id, owner, ("pending", "paused"), "cancelled")
        return self.store.get_task(task_id, owner)
