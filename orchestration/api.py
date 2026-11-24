"""Authenticated localhost API for task submission and inspection."""

import asyncio
import json
import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from orchestration.runtime import Runtime

app = FastAPI(title="Orin", docs_url=None, redoc_url=None, openapi_url=None)


class TaskRequest(BaseModel):
    session_id: str
    request: str
    idempotency_key: str | None = None


def authorized_owner(authorization: str | None = Header(default=None),
                     x_orin_user: str | None = Header(default=None)) -> str:
    token = os.getenv("ORIN_API_TOKEN", "")
    if not token or not authorization or not secrets.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(401, "Unauthorized")
    if not x_orin_user:
        raise HTTPException(400, "X-Orin-User is required")
    # The local API token grants access to this owner. Multi-user tokens are future work.
    owner = os.getenv("ORIN_API_USER", "local")
    if x_orin_user != owner:
        raise HTTPException(403, "Forbidden")
    return owner


def runtime() -> Runtime:
    return Runtime()


@app.post("/tasks")
async def submit_task(body: TaskRequest, owner: str = Depends(authorized_owner),
                      service: Runtime = Depends(runtime)):
    try:
        task = await service.submit(owner, body.session_id, body.request, body.idempotency_key)
    except PermissionError:
        raise HTTPException(403, "Forbidden") from None
    return {"id": task["id"], "status": task["status"]}


@app.post("/tasks/{task_id}/run")
async def run_task(task_id: str, owner: str = Depends(authorized_owner),
                   service: Runtime = Depends(runtime)):
    try:
        return await service.run(owner, task_id)
    except KeyError:
        raise HTTPException(404, "Task not found") from None
    except PermissionError:
        raise HTTPException(403, "Forbidden") from None


@app.get("/tasks/{task_id}")
def get_task(task_id: str, owner: str = Depends(authorized_owner),
             service: Runtime = Depends(runtime)):
    task = service.store.get_task(task_id, owner)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


@app.get("/tasks")
def list_tasks(session_id: str | None = None, owner: str = Depends(authorized_owner),
               service: Runtime = Depends(runtime)):
    return service.store.list_tasks(owner, session_id)


@app.get("/sessions")
def list_sessions(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.store.list_sessions(owner)


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str, owner: str = Depends(authorized_owner),
                     service: Runtime = Depends(runtime)):
    messages = service.store.messages(owner, session_id)
    if messages is None:
        raise HTTPException(404, "Session not found")
    return messages


@app.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, owner: str = Depends(authorized_owner),
                service: Runtime = Depends(runtime)):
    try:
        return service.cancel(owner, task_id)
    except KeyError:
        raise HTTPException(404, "Task not found") from None


@app.get("/tasks/{task_id}/events")
async def stream_events(task_id: str, after: int = 0, owner: str = Depends(authorized_owner),
                        service: Runtime = Depends(runtime)):
    if service.store.get_task(task_id, owner) is None:
        raise HTTPException(404, "Task not found")

    async def events():
        cursor = after
        while True:
            for event in service.store.events(task_id, cursor):
                cursor = event["id"]
                yield f"id: {cursor}\nevent: {event['name']}\ndata: {json.dumps(event)}\n\n"
            task = service.store.get_task(task_id, owner)
            if task["status"] in ("completed", "cancelled"):
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")
