"""Durable, owner-scoped scheduling that dispatches through the shared runtime.

The scheduler does not execute tasks itself. Each occurrence has a stable
idempotency key, so a restart between submission and acknowledgement reuses the
same Runtime task. A caller invokes ``dispatch_due`` from its local worker loop.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Schedule times must include a timezone")
    return value.astimezone(UTC)


def _stamp(value: datetime) -> str:
    return _aware(value).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _local_wall(day: date, hour: int, minute: int, zone: ZoneInfo) -> datetime:
    """Use the first occurrence of an ambiguous time, or the next valid minute."""
    wall = datetime.combine(day, time(hour, minute))
    for _ in range(181):
        candidate = wall.replace(tzinfo=zone, fold=0)
        if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == wall:
            return candidate.astimezone(UTC)
        wall += timedelta(minutes=1)
    raise ValueError("No valid local scheduling time found")


def next_daily_run(after: datetime, timezone_name: str, hour: int, minute: int) -> datetime:
    after = _aware(after)
    if not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError("Daily time is outside 00:00–23:59")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ValueError("Unknown IANA time zone") from error
    local_day = after.astimezone(zone).date()
    for days in range(0, 3):
        candidate = _local_wall(local_day + timedelta(days=days), hour, minute, zone)
        if candidate > after:
            return candidate
    raise RuntimeError("Could not calculate the next daily occurrence")


@dataclass(frozen=True)
class DueRun:
    id: str
    job_id: str
    owner: str
    session_id: str
    request: str
    scheduled_for: str

    @property
    def idempotency_key(self) -> str:
        return f"schedule:{self.job_id}:{self.scheduled_for}"


class ScheduledJobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, session_id TEXT NOT NULL,
                    request TEXT NOT NULL, timezone TEXT NOT NULL,
                    recurrence TEXT NOT NULL CHECK(recurrence IN ('once','daily')),
                    hour INTEGER, minute INTEGER,
                    misfire_policy TEXT NOT NULL CHECK(misfire_policy IN ('skip','run_once')),
                    grace_seconds INTEGER NOT NULL,
                    next_run_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','finished','missed','cancelled')),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS scheduled_jobs_due
                    ON scheduled_jobs(status, next_run_at);
                CREATE TABLE IF NOT EXISTS scheduled_runs (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, owner TEXT NOT NULL,
                    scheduled_for TEXT NOT NULL, status TEXT NOT NULL,
                    task_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    claimed_until TEXT, updated_at TEXT NOT NULL,
                    UNIQUE(job_id, scheduled_for),
                    FOREIGN KEY(job_id) REFERENCES scheduled_jobs(id)
                );
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def create_once(self, owner: str, session_id: str, request: str, run_at: datetime,
                    *, timezone_name: str = "UTC", misfire_policy: str = "run_once",
                    grace_seconds: int = 300) -> dict:
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Unknown IANA time zone") from error
        return self._create(owner, session_id, request, _aware(run_at), timezone_name,
                            "once", None, None, misfire_policy, grace_seconds)

    def create_daily(self, owner: str, session_id: str, request: str,
                     timezone_name: str, hour: int, minute: int,
                     *, after: datetime | None = None, misfire_policy: str = "run_once",
                     grace_seconds: int = 300) -> dict:
        after = _aware(after or datetime.now(UTC))
        next_at = next_daily_run(after, timezone_name, hour, minute)
        return self._create(owner, session_id, request, next_at, timezone_name,
                            "daily", hour, minute, misfire_policy, grace_seconds)

    def _create(self, owner: str, session_id: str, request: str, next_at: datetime,
                timezone_name: str, recurrence: str, hour: int | None, minute: int | None,
                misfire_policy: str, grace_seconds: int) -> dict:
        if not owner or not session_id or not request.strip() or len(request) > 4000:
            raise ValueError("Owner, session, and bounded request are required")
        if misfire_policy not in {"skip", "run_once"} or grace_seconds < 0:
            raise ValueError("Invalid missed-run policy or grace interval")
        now = datetime.now(UTC)
        job_id = str(uuid4())
        with self.connect() as db:
            db.execute("""INSERT INTO scheduled_jobs
                (id,owner,session_id,request,timezone,recurrence,hour,minute,
                 misfire_policy,grace_seconds,next_run_at,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'active',?)""",
                (job_id, owner, session_id, request, timezone_name, recurrence, hour, minute,
                 misfire_policy, grace_seconds, _stamp(next_at), _stamp(now)))
        return self.get(owner, job_id)

    def get(self, owner: str, job_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM scheduled_jobs WHERE id=? AND owner=?",
                             (job_id, owner)).fetchone()
            return dict(row) if row else None

    def list(self, owner: str) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM scheduled_jobs WHERE owner=? ORDER BY created_at DESC", (owner,))]

    def runs(self, owner: str, job_id: str) -> list[dict]:
        if self.get(owner, job_id) is None:
            raise KeyError("Scheduled job not found")
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM scheduled_runs WHERE owner=? AND job_id=? ORDER BY scheduled_for",
                (owner, job_id))]

    def cancel(self, owner: str, job_id: str) -> bool:
        with self.connect() as db:
            changed = db.execute("""UPDATE scheduled_jobs SET status='cancelled'
                WHERE id=? AND owner=? AND (status='active' OR
                    (status='finished' AND EXISTS (
                        SELECT 1 FROM scheduled_runs WHERE job_id=?
                          AND status IN ('claimed','retry'))))""",
                (job_id, owner, job_id)).rowcount
            if changed:
                db.execute("""UPDATE scheduled_runs SET status='cancelled'
                    WHERE job_id=? AND status IN ('claimed','retry')""", (job_id,))
            return bool(changed)

    def claim_due(self, now: datetime, *, lease_seconds: int = 60,
                  max_runs: int = 20) -> list[DueRun]:
        now = _aware(now)
        if lease_seconds < 1 or max_runs < 1:
            raise ValueError("Lease and run limits must be positive")
        stamp = _stamp(now)
        lease = _stamp(now + timedelta(seconds=lease_seconds))
        claimed: list[DueRun] = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute("""SELECT runs.*, jobs.session_id, jobs.request
                FROM scheduled_runs runs JOIN scheduled_jobs jobs ON jobs.id=runs.job_id
                WHERE jobs.status!='cancelled' AND runs.status IN ('claimed','retry')
                  AND runs.claimed_until<=? AND runs.attempts<3
                ORDER BY runs.scheduled_for LIMIT ?""", (stamp, max_runs)).fetchall()
            for row in pending:
                db.execute("""UPDATE scheduled_runs SET status='claimed', attempts=attempts+1,
                    claimed_until=?, updated_at=? WHERE id=?""", (lease, stamp, row["id"]))
                claimed.append(DueRun(row["id"], row["job_id"], row["owner"],
                                      row["session_id"], row["request"], row["scheduled_for"]))
            remaining = max_runs - len(claimed)
            if remaining:
                jobs = db.execute("""SELECT * FROM scheduled_jobs
                    WHERE status='active' AND next_run_at<=?
                    ORDER BY next_run_at LIMIT ?""", (stamp, remaining)).fetchall()
                for job in jobs:
                    scheduled_for = job["next_run_at"]
                    late = (now - _parse(scheduled_for)).total_seconds() > job["grace_seconds"]
                    skipped = late and job["misfire_policy"] == "skip"
                    run_id = str(uuid4())
                    db.execute("""INSERT OR IGNORE INTO scheduled_runs
                        (id,job_id,owner,scheduled_for,status,attempts,claimed_until,updated_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (run_id, job["id"], job["owner"], scheduled_for,
                         "skipped" if skipped else "claimed", 0 if skipped else 1,
                         None if skipped else lease, stamp))
                    if job["recurrence"] == "once":
                        next_status = "missed" if skipped else "finished"
                        db.execute("UPDATE scheduled_jobs SET status=? WHERE id=?",
                                   (next_status, job["id"]))
                    else:
                        next_at = next_daily_run(now, job["timezone"], job["hour"], job["minute"])
                        db.execute("UPDATE scheduled_jobs SET next_run_at=? WHERE id=?",
                                   (_stamp(next_at), job["id"]))
                    if not skipped:
                        claimed.append(DueRun(run_id, job["id"], job["owner"],
                                              job["session_id"], job["request"], scheduled_for))
        return claimed

    def finish_run(self, owner: str, run_id: str, status: str, task_id: str | None = None,
                   *, now: datetime | None = None) -> bool:
        if status not in {"completed", "paused", "retry", "cancelled"}:
            raise ValueError("Invalid scheduled run status")
        when = _aware(now or datetime.now(UTC))
        stamp = _stamp(when)
        retry_after = _stamp(when + timedelta(seconds=30)) if status == "retry" else None
        with self.connect() as db:
            return bool(db.execute("""UPDATE scheduled_runs SET status=?, task_id=COALESCE(?,task_id),
                claimed_until=?, updated_at=? WHERE id=? AND owner=? AND status='claimed'""",
                (status, task_id, retry_after, stamp, run_id, owner)).rowcount)


async def dispatch_due(store: ScheduledJobStore, runtime, now: datetime | None = None) -> list[dict]:
    """Dispatch due runs through Runtime.submit/run; never construct another agent."""
    outcomes = []
    when = _aware(now or datetime.now(UTC))
    for due in store.claim_due(when):
        job = store.get(due.owner, due.job_id)
        if job is None or job["status"] == "cancelled":
            store.finish_run(due.owner, due.id, "cancelled", now=when)
            continue
        task_id = None
        try:
            task = await runtime.submit(due.owner, due.session_id, due.request,
                                        idempotency_key=due.idempotency_key)
            task_id = task["id"]
            result = await runtime.run(due.owner, task_id)
            state = "completed" if result["status"] == "completed" else "paused"
            store.finish_run(due.owner, due.id, state, task_id, now=when)
            outcomes.append({"run_id": due.id, "task_id": task_id, "status": state})
        except Exception:
            store.finish_run(due.owner, due.id, "retry", task_id, now=when)
            outcomes.append({"run_id": due.id, "task_id": task_id, "status": "retry"})
    return outcomes
