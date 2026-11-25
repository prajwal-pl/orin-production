"""Authenticated localhost API for task submission and inspection."""

import asyncio
import json
import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from orchestration.runtime import Runtime
from orchestration.integrations import SOURCES, connected_sources

app = FastAPI(title="Orin", docs_url=None, redoc_url=None, openapi_url=None)


class TaskRequest(BaseModel):
    session_id: str
    request: str
    idempotency_key: str | None = None


class MemoryRequest(BaseModel):
    category: str
    content: str
    provenance: str = "user"


class MemoryCorrection(BaseModel):
    content: str


class CustomSkillRequest(BaseModel):
    priority_reasons: list[str]


class BriefingSkillRequest(BaseModel):
    source_order: list[str]


class TaskCorrection(BaseModel):
    content: str


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


@app.get("/tasks/{task_id}/usage")
def task_usage(task_id: str, owner: str = Depends(authorized_owner),
               service: Runtime = Depends(runtime)):
    if service.store.get_task(task_id, owner) is None:
        raise HTTPException(404, "Task not found")
    return service.store.usage_for_task(task_id)


@app.get("/tasks")
def list_tasks(session_id: str | None = None, owner: str = Depends(authorized_owner),
               service: Runtime = Depends(runtime)):
    return service.store.list_tasks(owner, session_id)


@app.get("/sessions")
def list_sessions(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.store.list_sessions(owner)


@app.get("/models")
def list_models(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.store.list_model_health()


@app.get("/capabilities")
def list_capabilities(owner: str = Depends(authorized_owner)):
    connected = set(connected_sources(owner))
    return [{"key": source.key, "capability": source.capability,
             "description": source.description, "oauth_scope": source.oauth_scope,
             "read_only": source.read_only, "configured": source.key in connected}
            for source in SOURCES.values()]


@app.post("/memories")
def add_memory(body: MemoryRequest, owner: str = Depends(authorized_owner),
               service: Runtime = Depends(runtime)):
    try:
        return service.memory.add(owner, body.category, body.content, body.provenance)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.get("/memories")
def list_memories(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.memory.list(owner)


@app.get("/memories/search")
def search_memories(q: str, owner: str = Depends(authorized_owner),
                    service: Runtime = Depends(runtime)):
    return service.memory.search(owner, q)


@app.get("/memories/export")
def export_memories(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.memory.export(owner)


@app.get("/memories/{memory_id}")
def get_memory(memory_id: str, owner: str = Depends(authorized_owner),
               service: Runtime = Depends(runtime)):
    memory = service.memory.get(owner, memory_id)
    if memory is None:
        raise HTTPException(404, "Memory not found")
    return memory


@app.put("/memories/{memory_id}")
def correct_memory(memory_id: str, body: MemoryCorrection, owner: str = Depends(authorized_owner),
                   service: Runtime = Depends(runtime)):
    try:
        return service.memory.correct(owner, memory_id, body.content)
    except KeyError:
        raise HTTPException(404, "Memory not found") from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: str, owner: str = Depends(authorized_owner),
                  service: Runtime = Depends(runtime)):
    try:
        service.memory.delete(owner, memory_id)
    except KeyError:
        raise HTTPException(404, "Memory not found") from None
    return {"deleted": True}


@app.get("/skills")
def list_skills(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.skills.list(owner)


@app.get("/skills/metrics")
def skill_metrics(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.skills.metrics(owner)


@app.post("/skills/custom")
def create_custom_skill(body: CustomSkillRequest, owner: str = Depends(authorized_owner),
                        service: Runtime = Depends(runtime)):
    try:
        return service.skills.create_custom(owner, body.priority_reasons)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.post("/skills/briefing")
def create_briefing_skill(body: BriefingSkillRequest, owner: str = Depends(authorized_owner),
                          service: Runtime = Depends(runtime)):
    try:
        return service.skills.create_briefing_custom(owner, body.source_order)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.get("/skills/{skill_id}")
def get_skill(skill_id: str, owner: str = Depends(authorized_owner),
              service: Runtime = Depends(runtime)):
    skill = service.skills.get(owner, skill_id)
    if skill is None:
        raise HTTPException(404, "Skill not found")
    return skill


@app.post("/skills/{skill_id}/activate")
def activate_skill(skill_id: str, owner: str = Depends(authorized_owner),
                   service: Runtime = Depends(runtime)):
    try:
        return service.skills.activate(owner, skill_id)
    except KeyError:
        raise HTTPException(404, "Skill not found") from None
    except PermissionError:
        raise HTTPException(403, "Skill permissions cannot expand") from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@app.get("/tasks/{task_id}/skill")
def task_skill(task_id: str, owner: str = Depends(authorized_owner),
               service: Runtime = Depends(runtime)):
    if service.store.get_task(task_id, owner) is None:
        raise HTTPException(404, "Task not found")
    with service.store.connect() as db:
        row = db.execute("""SELECT s.* FROM skill_executions e
            JOIN skill_versions s ON s.id=e.skill_id WHERE e.task_id=? AND s.owner=?""",
            (task_id, owner)).fetchone()
    return dict(row) if row else None


@app.post("/tasks/{task_id}/corrections")
def add_task_correction(task_id: str, body: TaskCorrection,
                        owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    try:
        return service.skills.correction(owner, task_id, body.content)
    except KeyError:
        raise HTTPException(404, "Completed task not found") from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


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
