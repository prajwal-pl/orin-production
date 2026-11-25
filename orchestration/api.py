"""Authenticated localhost API for task submission and inspection."""

import asyncio
import json
import os
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from orchestration.google_oauth import disconnect as disconnect_google, has_refresh_token, refreshed_access_token
from orchestration.google_writes import WRITE_SOURCES
from orchestration.integrations import MissingCredential, SOURCES, authorize_source, connected_sources
from orchestration.local_tools import IsolatedBrowser, ScopedFileSystem, ScopedTerminal
from orchestration.policy import PolicyDenied
from orchestration.runtime import Runtime
from orchestration.web_assets import attach_web_assets
from orchestration.web_auth import COOKIE_NAME, SESSION_SECONDS, web_auth

app = FastAPI(title="Orin", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


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


class GrantRequest(BaseModel):
    capability: str
    operation: str


class RootGrantRequest(BaseModel):
    path: str
    operation: str = "read"


class ActionRequest(BaseModel):
    capability: str
    parameters: dict
    idempotency_key: str


class ScheduleRequest(BaseModel):
    session_id: str
    request: str
    recurrence: str
    timezone: str = "UTC"
    run_at: datetime | None = None
    hour: int | None = None
    minute: int | None = None
    misfire_policy: str = "run_once"


class DelegationRequest(BaseModel):
    parent_task_id: str
    request: str
    allowed_capabilities: list[str]
    max_model_calls: int = 0
    max_model_tokens: int = 0


class SyncRequest(BaseModel):
    account_id: str


class LocalIndexRequest(BaseModel):
    root: str
    relative_paths: list[str]


class FileReadRequest(BaseModel):
    path: str


class FileWriteRequest(BaseModel):
    path: str
    content: str
    approval_id: str | None = None


class TerminalRequest(BaseModel):
    argv: list[str]
    root: str
    approval_id: str | None = None


class BrowserRequest(BaseModel):
    url: str


class MCPServerRequest(BaseModel):
    server_id: str
    endpoint: str
    allowed_tools: list[str]


class MCPCallRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)


class PairRequest(BaseModel):
    code: str


def phase4_error(error: Exception) -> HTTPException:
    if isinstance(error, KeyError):
        return HTTPException(404, "Resource not found")
    if isinstance(error, (PolicyDenied, PermissionError)):
        return HTTPException(403, str(error))
    if isinstance(error, (ValueError, MissingCredential)):
        return HTTPException(400, str(error))
    return HTTPException(502, "Capability failed; inspect its audit status")


def authorized_owner(request: Request,
                     authorization: str | None = Header(default=None),
                     x_orin_user: str | None = Header(default=None)) -> str:
    if authorization is None and request.cookies.get(COOKIE_NAME):
        return web_auth.authorize_cookie(request, x_orin_user).owner
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


@app.get("/auth/bootstrap")
def browser_bootstrap():
    return {"pairing_available": web_auth.pairing_available()}


@app.post("/auth/pair")
def pair_browser(body: PairRequest, request: Request, response: Response):
    web_auth.check_origin(request)
    token, session = web_auth.pair(body.code)
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        samesite="strict", path="/")
    return {"owner": session.owner, "csrf": session.csrf, "expires_at": session.expires_at}


@app.get("/auth/session")
def browser_session(request: Request):
    session = web_auth.authorize_cookie(request, None)
    return {"owner": session.owner, "csrf": session.csrf, "expires_at": session.expires_at}


@app.post("/auth/logout")
def logout_browser(request: Request, response: Response):
    web_auth.authorize_cookie(request, None)
    web_auth.logout(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"logged_out": True}


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


@app.get("/usage")
def usage_summary(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.store.usage_summary(owner)


@app.get("/capabilities")
def list_capabilities(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    connected = set(connected_sources(owner))
    successful = service.store.last_successful_capabilities(owner)
    return [{"key": source.key, "capability": source.capability,
             "description": source.description, "oauth_scope": source.oauth_scope,
             "read_only": source.read_only, "configured": source.key in connected,
             "auth_method": ("environment" if os.getenv(source.token_env, "").strip()
                             else "oauth" if source.key in {"gmail", "drive", "calendar"}
                             and has_refresh_token(owner, source.key) else None),
             "last_success_at": successful.get(source.capability)}
            for source in SOURCES.values()]


@app.post("/connections/{source}/disconnect")
async def disconnect_source(source: str, owner: str = Depends(authorized_owner)):
    if source not in {"gmail", "drive", "calendar"}:
        raise HTTPException(404, "OAuth connection not found")
    if os.getenv(SOURCES[source].token_env, "").strip():
        raise HTTPException(409, "This source uses an environment token; remove it from local configuration")
    try:
        await disconnect_google(owner, source)
    except Exception:
        raise HTTPException(502, "Could not remove the local credential") from None
    return {"source": source, "disconnected": True}


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


@app.post("/policy/grants")
def grant_capability(body: GrantRequest, owner: str = Depends(authorized_owner),
                     service: Runtime = Depends(runtime)):
    known_read = {item.capability for item in SOURCES.values()} | {"filesystem", "browser", "search.content"}
    known_write = set(WRITE_SOURCES) | {"filesystem", "terminal"}
    if (body.operation == "read" and (body.capability in known_read or body.capability.startswith("mcp.")) or
            body.operation == "write" and body.capability in known_write):
        service.policy.grant(owner, body.capability, body.operation)
        return {"capability": body.capability, "operation": body.operation, "granted": True}
    raise HTTPException(400, "Unknown capability or operation")


@app.post("/policy/roots")
def grant_filesystem_root(body: RootGrantRequest, owner: str = Depends(authorized_owner),
                          service: Runtime = Depends(runtime)):
    try:
        root = service.policy.grant_root(owner, Path(body.path), body.operation)
        return {"path": str(root), "operation": body.operation}
    except Exception as error:
        raise phase4_error(error) from None


@app.get("/policy/audit")
def policy_audit(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.policy.audit_for_owner(owner)


@app.get("/approvals")
def approvals(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.policy.list_approvals(owner)


@app.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, owner: str = Depends(authorized_owner),
            service: Runtime = Depends(runtime)):
    try:
        return service.policy.approve(owner, approval_id)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/approvals/{approval_id}/deny")
def deny(approval_id: str, owner: str = Depends(authorized_owner),
         service: Runtime = Depends(runtime)):
    try:
        return service.policy.deny(owner, approval_id)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/actions")
def prepare_action(body: ActionRequest, owner: str = Depends(authorized_owner),
                   service: Runtime = Depends(runtime)):
    try:
        return service.actions.prepare(owner, body.capability, body.parameters, body.idempotency_key)
    except Exception as error:
        raise phase4_error(error) from None


@app.get("/actions")
def list_actions(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.actions.list(owner)


@app.get("/actions/{action_id}")
def get_action(action_id: str, owner: str = Depends(authorized_owner),
               service: Runtime = Depends(runtime)):
    action = service.actions.get(owner, action_id)
    if action is None:
        raise HTTPException(404, "Action not found")
    return action


@app.post("/actions/{action_id}/run")
async def run_action(action_id: str, owner: str = Depends(authorized_owner),
                     service: Runtime = Depends(runtime)):
    try:
        return await service.actions.execute(owner, action_id)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/actions/{action_id}/reconcile")
async def reconcile_action(action_id: str, owner: str = Depends(authorized_owner),
                           service: Runtime = Depends(runtime)):
    try:
        return await service.actions.reconcile(owner, action_id)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/sync/{source}")
async def sync_source(source: str, body: SyncRequest, owner: str = Depends(authorized_owner),
                      service: Runtime = Depends(runtime)):
    if source not in {"gmail", "drive", "calendar"}:
        raise HTTPException(400, "Only Google read sources support incremental sync")
    try:
        authorize_source(owner, source)
        token = os.getenv(SOURCES[source].token_env, "").strip()
        if not token:
            if not has_refresh_token(owner, source):
                raise MissingCredential(f"{source} is not connected")
            token = await refreshed_access_token(owner, source)
        result = await service.sync_engine.sync(owner, source, body.account_id, token)
        return result.__dict__
    except Exception as error:
        raise phase4_error(error) from None


@app.get("/search")
def search_sources(q: str, include_content: bool = False, account_id: str | None = None,
                   sources: str | None = None, owner: str = Depends(authorized_owner),
                   service: Runtime = Depends(runtime)):
    try:
        if include_content:
            service.policy.authorize(owner, "search.content", "read")
        selected = set(sources.split(",")) if sources else None
        return [hit.__dict__ for hit in service.search.search(
            owner, q, include_content=include_content, account_id=account_id, sources=selected)]
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/search/index-local")
def index_local(body: LocalIndexRequest, owner: str = Depends(authorized_owner),
                service: Runtime = Depends(runtime)):
    try:
        root = Path(body.root).resolve(strict=True)
        if root not in service.policy.roots(owner, "read"):
            raise PolicyDenied("Local index root is not approved")
        service.policy.authorize(owner, "filesystem", "read")
        count = service.search.index_local_files(owner, root, body.relative_paths)
        return {"indexed": count}
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/schedules")
def create_schedule(body: ScheduleRequest, owner: str = Depends(authorized_owner),
                    service: Runtime = Depends(runtime)):
    try:
        if body.recurrence == "once" and body.run_at:
            return service.schedules.create_once(owner, body.session_id, body.request, body.run_at,
                                                 timezone_name=body.timezone,
                                                 misfire_policy=body.misfire_policy)
        if body.recurrence == "daily" and body.hour is not None and body.minute is not None:
            return service.schedules.create_daily(owner, body.session_id, body.request,
                                                  body.timezone, body.hour, body.minute,
                                                  misfire_policy=body.misfire_policy)
        raise ValueError("A once schedule needs run_at; daily needs hour and minute")
    except Exception as error:
        raise phase4_error(error) from None


@app.get("/schedules")
def list_schedules(owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    return service.schedules.list(owner)


@app.get("/schedules/{job_id}/runs")
def schedule_runs(job_id: str, owner: str = Depends(authorized_owner),
                  service: Runtime = Depends(runtime)):
    try:
        return service.schedules.runs(owner, job_id)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/schedules/{job_id}/cancel")
def cancel_schedule(job_id: str, owner: str = Depends(authorized_owner),
                    service: Runtime = Depends(runtime)):
    return {"cancelled": service.schedules.cancel(owner, job_id)}


@app.post("/delegations")
def create_delegation(body: DelegationRequest, owner: str = Depends(authorized_owner),
                      service: Runtime = Depends(runtime)):
    try:
        spec = service.create_delegation(owner, body.parent_task_id, body.request,
                                         set(body.allowed_capabilities), body.max_model_calls,
                                         body.max_model_tokens)
        return spec.__dict__ | {"allowed_capabilities": sorted(spec.allowed_capabilities)}
    except Exception as error:
        raise phase4_error(error) from None


@app.get("/tasks/{task_id}/delegations")
def delegation_progress(task_id: str, owner: str = Depends(authorized_owner),
                        service: Runtime = Depends(runtime)):
    if service.store.get_task(task_id, owner) is None:
        raise HTTPException(404, "Task not found")
    return service.delegations.progress(owner, task_id)


@app.post("/delegations/{child_id}/run")
async def run_delegation(child_id: str, owner: str = Depends(authorized_owner),
                         service: Runtime = Depends(runtime)):
    try:
        return await service.run_delegation(owner, child_id)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/delegations/{child_id}/cancel")
def cancel_delegation(child_id: str, owner: str = Depends(authorized_owner),
                      service: Runtime = Depends(runtime)):
    child = service.cancel_delegation(owner, child_id)
    if child is None:
        raise HTTPException(404, "Delegation not found")
    return child


@app.post("/tools/files/read")
def read_file(body: FileReadRequest, owner: str = Depends(authorized_owner),
              service: Runtime = Depends(runtime)):
    try:
        content = ScopedFileSystem(service.policy, owner).read(Path(body.path))
        return {"content": content.decode("utf-8", errors="replace"), "untrusted": True}
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/tools/files/prepare-write")
def prepare_file_write(body: FileWriteRequest, owner: str = Depends(authorized_owner),
                       service: Runtime = Depends(runtime)):
    content = body.content.encode("utf-8")
    parameters = ScopedFileSystem.write_parameters(Path(body.path), content)
    try:
        return service.policy.request_approval(owner, "filesystem", parameters)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/tools/files/write-new")
def write_file(body: FileWriteRequest, owner: str = Depends(authorized_owner),
               service: Runtime = Depends(runtime)):
    if not body.approval_id:
        raise HTTPException(400, "approval_id is required")
    try:
        ScopedFileSystem(service.policy, owner).write_new(
            Path(body.path), body.content.encode("utf-8"), body.approval_id)
        return {"created": True}
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/tools/terminal/prepare")
def prepare_terminal(body: TerminalRequest, owner: str = Depends(authorized_owner),
                     service: Runtime = Depends(runtime)):
    try:
        parameters = ScopedTerminal.run_parameters(body.argv, Path(body.root))
        return service.policy.request_approval(owner, "terminal", parameters)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/tools/terminal/run")
def run_terminal(body: TerminalRequest, owner: str = Depends(authorized_owner),
                 service: Runtime = Depends(runtime)):
    if not body.approval_id:
        raise HTTPException(400, "approval_id is required")
    try:
        return ScopedTerminal(service.policy, owner).run(body.argv, Path(body.root), body.approval_id).__dict__
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/tools/browser/fetch")
def browser_fetch(body: BrowserRequest, owner: str = Depends(authorized_owner),
                  service: Runtime = Depends(runtime)):
    try:
        return IsolatedBrowser(service.policy, owner).fetch(body.url).__dict__
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/mcp/servers")
def register_mcp(body: MCPServerRequest, owner: str = Depends(authorized_owner),
                 service: Runtime = Depends(runtime)):
    try:
        return service.mcp.register(owner, body.server_id, body.endpoint, body.allowed_tools)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/mcp/servers/{server_id}/trust")
def trust_mcp(server_id: str, owner: str = Depends(authorized_owner),
              service: Runtime = Depends(runtime)):
    try:
        return service.mcp.trust(owner, server_id)
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/mcp/servers/{server_id}/revoke")
def revoke_mcp(server_id: str, owner: str = Depends(authorized_owner),
               service: Runtime = Depends(runtime)):
    service.mcp.revoke(owner, server_id)
    return {"revoked": True}


@app.get("/mcp/servers/{server_id}/tools")
async def mcp_tools(server_id: str, owner: str = Depends(authorized_owner),
                    service: Runtime = Depends(runtime)):
    try:
        return {"tools": await service.mcp.list_tools(owner, server_id)}
    except Exception as error:
        raise phase4_error(error) from None


@app.post("/mcp/servers/{server_id}/tools/{tool}")
async def mcp_call(server_id: str, tool: str, body: MCPCallRequest,
                   owner: str = Depends(authorized_owner), service: Runtime = Depends(runtime)):
    try:
        observation = await service.mcp.call(owner, server_id, tool, body.arguments)
        return observation.__dict__
    except Exception as error:
        raise phase4_error(error) from None


attach_web_assets(app)
