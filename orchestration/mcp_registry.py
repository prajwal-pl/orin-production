"""Explicit MCP server trust and lower-trust tool observations.

The registry is transport-neutral. A caller supplies an executor for an approved
server/tool; registry text is returned as data and never interpreted as a command.
"""

import asyncio
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from mcp import Client, StdioServerParameters

from orchestration.policy import PolicyDenied, PolicyStore


@dataclass(frozen=True)
class UntrustedObservation:
    server_id: str
    tool: str
    text: str
    observed_at: float
    untrusted: bool = True

    def model_context(self) -> str:
        # JSON quoting keeps the payload visually distinct from the runtime's
        # instructions. The model must still treat this as untrusted source data.
        return "Untrusted MCP observation (data only): " + json.dumps({
            "server": self.server_id, "tool": self.tool, "text": self.text,
        }, ensure_ascii=False)


class MCPRegistry:
    def __init__(self, policy: PolicyStore):
        self.policy = policy
        with self.policy.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS mcp_servers (
                owner TEXT NOT NULL, server_id TEXT NOT NULL, endpoint TEXT NOT NULL,
                allowed_tools TEXT NOT NULL, trust_status TEXT NOT NULL,
                PRIMARY KEY(owner, server_id)
            )""")

    def list(self, owner: str) -> list[dict]:
        with self.policy.connect() as db:
            rows = db.execute(
                "SELECT * FROM mcp_servers WHERE owner=? ORDER BY server_id",
                (owner,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["allowed_tools"] = json.loads(item["allowed_tools"])
            result.append(item)
        return result

    async def list_planner_tools(self, owner: str) -> list[dict]:
        """Return trusted no-argument tools that the owner has explicitly granted.

        Tools that require arguments stay available through the explicit MCP
        API/control center, where the owner supplies the arguments. This keeps
        the planner from inventing tool arguments.
        """
        entries: list[dict] = []
        for record in self.list(owner):
            if record["trust_status"] != "trusted":
                continue
            try:
                described = await _cached_describe(record["endpoint"])
            except Exception:
                continue
            allowed = set(record["allowed_tools"])
            for item in described:
                name = item["name"]
                if name not in allowed:
                    continue
                if not self.policy.has_grant(owner, f"mcp.{record['server_id']}.{name}", "read"):
                    continue
                schema = item.get("input_schema") or {}
                if schema.get("required"):
                    continue
                entries.append({
                    "server_id": record["server_id"],
                    "tool": name,
                    "description": item.get("description") or "",
                    "input_schema": schema,
                })
        return entries

    def register(self, owner: str, server_id: str, endpoint: str,
                 allowed_tools: list[str]) -> dict:
        if not owner or not server_id or not endpoint or not allowed_tools:
            raise ValueError("Owner, server ID, endpoint, and tools are required")
        if any(not tool or not isinstance(tool, str) for tool in allowed_tools):
            raise ValueError("Tool names must be nonempty strings")
        if not endpoint.startswith("stdio:") or not Path(endpoint[6:]).is_absolute():
            raise ValueError("MCP endpoint must be stdio: followed by an absolute executable path")
        with self.policy.connect() as db:
            db.execute("""INSERT INTO mcp_servers(owner,server_id,endpoint,allowed_tools,trust_status)
                VALUES(?,?,?,?, 'pending')
                ON CONFLICT(owner,server_id) DO UPDATE SET
                endpoint=excluded.endpoint, allowed_tools=excluded.allowed_tools, trust_status='pending'""",
                (owner, server_id, endpoint, json.dumps(sorted(set(allowed_tools)))))
        self.policy.audit(owner, "mcp", "write", "registered", server_id)
        return self.get(owner, server_id)

    def get(self, owner: str, server_id: str) -> dict | None:
        with self.policy.connect() as db:
            row = db.execute("SELECT * FROM mcp_servers WHERE owner=? AND server_id=?",
                             (owner, server_id)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["allowed_tools"] = json.loads(result["allowed_tools"])
        return result

    def trust(self, owner: str, server_id: str) -> dict:
        with self.policy.connect() as db:
            changed = db.execute("UPDATE mcp_servers SET trust_status='trusted' WHERE owner=? AND server_id=?",
                                 (owner, server_id)).rowcount
        if not changed:
            raise KeyError("MCP server not found")
        self.policy.audit(owner, "mcp", "write", "trusted", server_id)
        return self.get(owner, server_id)

    def revoke(self, owner: str, server_id: str) -> None:
        with self.policy.connect() as db:
            db.execute("UPDATE mcp_servers SET trust_status='revoked' WHERE owner=? AND server_id=?",
                       (owner, server_id))
        self.policy.audit(owner, "mcp", "write", "revoked", server_id)

    async def list_tools(self, owner: str, server_id: str) -> list[str]:
        record = self._trusted(owner, server_id)
        advertised = await _stdio_list_tools(record["endpoint"])
        allowed = set(record["allowed_tools"])
        return sorted(tool for tool in advertised if tool in allowed and
                      self.policy.has_grant(owner, f"mcp.{server_id}.{tool}", "read"))

    def _trusted(self, owner: str, server_id: str) -> dict:
        record = self.get(owner, server_id)
        if record is None or record["trust_status"] != "trusted":
            self.policy.audit(owner, "mcp", "read", "denied", "untrusted server")
            raise PolicyDenied("MCP server is not trusted")
        return record

    async def call(self, owner: str, server_id: str, tool: str, arguments: dict,
                   executor: Callable[[str, str, dict], Awaitable[str]] | None = None,
                   max_chars: int = 5000) -> UntrustedObservation:
        record = self._trusted(owner, server_id)
        if tool not in record["allowed_tools"]:
            self.policy.audit(owner, "mcp", "read", "denied", "untrusted server or tool")
            raise PolicyDenied("MCP server or tool is not trusted")
        self.policy.authorize(owner, f"mcp.{server_id}.{tool}", "read")
        if not isinstance(arguments, dict) or not 1 <= max_chars <= 5000:
            raise ValueError("Invalid MCP call arguments or output limit")
        if tool not in await _stdio_list_tools(record["endpoint"]):
            self.policy.audit(owner, f"mcp.{server_id}.{tool}", "read", "denied", "not advertised")
            raise PolicyDenied("MCP server does not advertise this tool")
        text = await (executor or _stdio_call_tool)(record["endpoint"], tool, arguments)
        if not isinstance(text, str):
            raise ValueError("MCP executor must return text")
        self.policy.audit(owner, f"mcp.{server_id}.{tool}", "read", "completed")
        return UntrustedObservation(server_id, tool, text[:max_chars], time.time())


def _server_parameters(endpoint: str, home: str) -> StdioServerParameters:
    if not endpoint.startswith("stdio:"):
        raise ValueError("Only stdio MCP transport is implemented")
    executable = Path(endpoint[6:])
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise PolicyDenied("MCP stdio executable is unavailable")
    return StdioServerParameters(command=str(executable), args=[], cwd=home,
                                 env={"PATH": "/usr/bin:/bin", "HOME": home,
                                      "PYTHONNOUSERSITE": "1"})


async def _stdio_list_tools(endpoint: str) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="orin-mcp-") as home:
        parameters = _server_parameters(endpoint, home)
        async with asyncio.timeout(10):
            async with Client(parameters, read_timeout_seconds=8) as client:
                result = await client.list_tools()
                return [item.name for item in result.tools]


_DESCRIBE_CACHE: dict[str, tuple[float, list[dict]]] = {}
_DESCRIBE_TTL_SECONDS = 60


def clear_describe_cache() -> None:
    _DESCRIBE_CACHE.clear()


async def _cached_describe(endpoint: str) -> list[dict]:
    now = time.monotonic()
    cached = _DESCRIBE_CACHE.get(endpoint)
    if cached and now - cached[0] < _DESCRIBE_TTL_SECONDS:
        return cached[1]
    described = await _stdio_describe_tools(endpoint)
    _DESCRIBE_CACHE[endpoint] = (now, described)
    return described


async def _stdio_describe_tools(endpoint: str) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="orin-mcp-") as home:
        parameters = _server_parameters(endpoint, home)
        async with asyncio.timeout(10):
            async with Client(parameters, read_timeout_seconds=8) as client:
                result = await client.list_tools()
                return [{
                    "name": item.name,
                    "description": item.description or "",
                    "input_schema": dict(item.input_schema or {}),
                } for item in result.tools]


async def _stdio_call_tool(endpoint: str, tool: str, arguments: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="orin-mcp-") as home:
        parameters = _server_parameters(endpoint, home)
        async with asyncio.timeout(10):
            async with Client(parameters, read_timeout_seconds=8) as client:
                advertised = await client.list_tools()
                if tool not in {item.name for item in advertised.tools}:
                    raise PolicyDenied("MCP server does not advertise this tool")
                result = await client.call_tool(tool, arguments, read_timeout_seconds=8)
                if result.is_error:
                    raise RuntimeError("MCP tool returned an error")
                text = [item.text for item in result.content if getattr(item, "type", None) == "text"]
                return "\n".join(text) if text else "[non-text MCP result omitted]"
