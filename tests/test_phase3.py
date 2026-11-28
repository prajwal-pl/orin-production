import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from evaluation.learning import crowded_notifications
from orchestration import runtime
from orchestration.api import app
from orchestration.memory import MemoryStore
from orchestration.runtime import Runtime
from orchestration.skills import SkillRegistry
from orchestration.store import TaskStore


@pytest.fixture
def phase3_env(monkeypatch, tmp_path):
    path = tmp_path / "orin.db"
    monkeypatch.setenv("ORIN_DATABASE_PATH", str(path))
    monkeypatch.setenv("ORIN_GITHUB_ALLOWED_USERS", "local")
    monkeypatch.setenv("ORIN_MODEL", "scripted:primary")
    monkeypatch.setenv("ORIN_FALLBACK_MODEL", "")
    monkeypatch.setenv("ORIN_TASK_MODEL_CALLS", "0")
    monkeypatch.setenv("ORIN_API_TOKEN", "test-token")
    monkeypatch.setenv("ORIN_API_USER", "local")
    return path


def test_memory_owner_scope_correction_export_delete_and_rebuild(phase3_env):
    memory = MemoryStore(TaskStore(phase3_env))
    item = memory.add("local", "preference", "Prioritize security alerts", "user")
    other = memory.add("other", "semantic", "Private security note", "user")
    assert memory.get("other", item["id"]) is None
    assert memory.get("local", other["id"]) is None
    assert memory.search("local", "security alerts")[0]["id"] == item["id"]
    corrected = memory.correct("local", item["id"], "Prioritize review requests")
    assert "user correction" in corrected["provenance"]
    assert memory.search("local", "review requests")[0]["id"] == item["id"]
    assert memory.export("local")[0]["content"] == "Prioritize review requests"
    memory.rebuild_index()
    assert memory.search("local", "review requests")[0]["id"] == item["id"]
    memory.delete("local", item["id"])
    assert memory.search("local", "review requests") == []
    with memory.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM memory_fts WHERE id=?", (item["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM memory_vectors WHERE memory_id=?", (item["id"],)).fetchone()[0] == 0


def test_expired_memory_prunes_all_indexes(phase3_env):
    memory = MemoryStore(TaskStore(phase3_env))
    item = memory.add("local", "working", "Temporary review context", "task:one")
    with memory.store.connect() as db:
        db.execute("UPDATE memories SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (item["id"],))
    assert memory.search("local", "review") == []
    with memory.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM memories WHERE id=?", (item["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM memory_fts WHERE id=?", (item["id"],)).fetchone()[0] == 0


def test_phase3_migration_from_version_six(phase3_env):
    TaskStore(phase3_env)
    with sqlite3.connect(phase3_env) as db:
        for table in ("user_corrections", "skill_executions", "skill_versions", "memory_vectors", "memory_fts", "memories"):
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=6")
    store = TaskStore(phase3_env)
    assert store.connect().execute("PRAGMA user_version").fetchone()[0] == 8
    assert MemoryStore(store).add("local", "semantic", "Review reminder", "user")


@pytest.mark.asyncio
async def test_skill_proposal_activation_rollback_and_attribution(phase3_env, monkeypatch):
    fetch = AsyncMock(return_value=crowded_notifications())
    monkeypatch.setattr(runtime, "fetch_notifications", fetch)
    service = Runtime(phase3_env)

    async def run(session):
        task = await service.submit("local", session, "Summarize my GitHub notifications")
        return await service.run("local", task["id"])

    baseline = await run("baseline")
    assert baseline["status"] == "completed"
    assert "Security alert" not in baseline["result"]
    skills = service.skills.list("local")
    builtin = next(skill for skill in skills if skill["kind"] == "builtin")
    proposal = next(skill for skill in skills if skill["kind"] == "learned")
    assert proposal["status"] == "proposed"
    evaluation = json.loads(proposal["evaluation"])
    assert evaluation["baseline"]["passed"] == 6
    assert evaluation["candidate"]["passed"] == 7
    assert service.skills.active("local")["id"] == builtin["id"]
    service.skills.correction("local", baseline["id"], "Security alert should be visible")

    service.skills.activate("local", proposal["id"])
    improved = await run("improved")
    assert improved["status"] == "completed"
    assert "Security alert" in improved["result"]
    with service.store.connect() as db:
        used = db.execute("SELECT skill_id FROM skill_executions WHERE task_id=?", (improved["id"],)).fetchone()[0]
    assert used == proposal["id"]
    metrics = {item["id"]: item for item in service.skills.metrics("local")}
    assert metrics[builtin["id"]]["corrections"] == 1
    assert metrics[proposal["id"]]["success_count"] == 1
    assert metrics[proposal["id"]]["model_calls"] == 0
    owner_key = __import__("hashlib").sha256(b"local").hexdigest()[:24]
    skill_file = Path(phase3_env).parent / "skills" / owner_key / "github_notifications_priority" / "v2" / "SKILL.md"
    assert skill_file.exists() and skill_file.stat().st_mode & 0o777 == 0o600

    service.skills.activate("local", builtin["id"])
    restored = await run("restored")
    assert "Security alert" not in restored["result"]
    assert fetch.await_count == 3
    assert len(service.skills.list("local")) == 2


def test_api_memory_and_skills_are_authenticated_and_scoped(phase3_env):
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token", "X-Orin-User": "local"}
    assert client.get("/memories").status_code == 401
    assert client.get("/skills", headers={**headers, "X-Orin-User": "other"}).status_code == 403
    created = client.post("/memories", headers=headers, json={
        "category": "preference", "content": "Show security alerts first", "provenance": "user",
    })
    assert created.status_code == 200
    memory_id = created.json()["id"]
    assert client.get("/memories/search", headers=headers, params={"q": "security alerts"}).json()[0]["id"] == memory_id
    assert client.put(f"/memories/{memory_id}", headers=headers, json={"content": "Show reviews first"}).status_code == 200
    assert client.get("/memories/export", headers=headers).json()[0]["content"] == "Show reviews first"
    assert client.delete(f"/memories/{memory_id}", headers=headers).json() == {"deleted": True}
    assert client.get(f"/memories/{memory_id}", headers=headers).status_code == 404
    assert client.post("/skills/custom", headers=headers, json={"priority_reasons": ["unknown"]}).status_code == 400
    custom = client.post("/skills/custom", headers=headers, json={"priority_reasons": ["security_alert"]})
    assert custom.status_code == 200
    assert custom.json()["status"] == "proposed"
    activated = client.post(f"/skills/{custom.json()['id']}/activate", headers=headers)
    assert activated.status_code == 200 and activated.json()["status"] == "active"
    builtin = next(skill for skill in client.get("/skills", headers=headers).json() if skill["kind"] == "builtin")
    assert client.post(f"/skills/{builtin['id']}/activate", headers=headers).json()["status"] == "active"
    assert client.get("/skills/metrics", headers=headers).status_code == 200


def test_skill_rejects_permission_expansion_and_invalid_procedures(phase3_env):
    registry = SkillRegistry(TaskStore(phase3_env))
    custom = registry.create_custom("local", ["security_alert"])
    with registry.store.connect() as db:
        db.execute("UPDATE skill_versions SET permissions=? WHERE id=?",
                   (json.dumps(["github:notifications", "filesystem:write"]), custom["id"]))
    with pytest.raises(PermissionError):
        registry.activate("local", custom["id"])
    with pytest.raises(ValueError):
        registry.create_custom("local", [["security_alert"]])
