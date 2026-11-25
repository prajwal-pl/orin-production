# Orin

**A local-first, self-adapting personal agent runtime.**

Orin is being built as one persistent agent that connects the services you
already use, remembers your context, learns reusable skills, and executes tasks
across local and cloud environments — through interfaces you already use, like
Telegram, instead of yet another chat window.

> The LLM is not the agent. The LLM is the reasoning engine inside a runtime that
> owns memory, state, tools, execution, learning, and budgets.

> **Status: Phase 5A local web control center implemented.**
> Telegram, CLI, a local API, and a browser UI share a SQLite-backed runtime. GitHub and
> Google read adapters have been checked against live accounts. Optional service
> adapters and Google write scopes still need live account verification. See
> [Current status](#current-status).

---

## Why this exists

Most agent projects are either a chat UI or a pile of integrations. Orin aims at
the harder, more useful middle:

- **Local-first ownership** — your memory, skills, credentials, and execution
  history live on infrastructure you control.
- **Free-tier realistic** — budget-aware context and model routing so limited
  quotas still complete real work.
- **Accessible from anywhere** — talk to the agent from Telegram/Discord/Slack
  while execution happens locally or in an always-on Hub.
- **Genuine continuity** — one identity and memory across every channel, not
  separate assistants per app.
- **Real learning** — successful workflows become versioned, reusable skills.
- **Transparency** — inspect what ran, which model was used, what it cost, and
  why it failed.

The design borrows the strongest ideas from two projects:

| Inspiration | What we borrow |
|---|---|
| [OpenClaw](https://github.com/openclaw/openclaw) | Tool runtime, browser/filesystem access, MCP, sessions, permissions |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | Persistent memory, experience-based learning, reusable skills |

---

## Current status

Phase 1 includes SQLite sessions, messages, tasks, events, execution records,
and LangGraph checkpoints. Telegram, a local CLI, and an authenticated localhost
API submit to the same runtime. A request containing both “GitHub” and
“notifications” fetches unread notifications, groups them by repository, and
prioritizes mentions, assignments, and review requests with source links. This
summary uses deterministic rules. Other GitHub requests still run the Phase 0
mock graph.

Phase 2 adds bounded context selection, local artifacts for tool output, a
per-task inference budget, model health and usage records, and fallback routing.
The GitHub workflow uses a local deterministic summary for fewer than five
notifications. Larger inboxes request model highlights from a bounded excerpt
and append the deterministic source list. When inference is unavailable or the
budget is exhausted, the workflow returns the local summary. Model calls in the
prototype graph also use task budgets. Session messages are retrieved
selectively for relevant context.

Phase 3 adds owner-scoped memory in SQLite with FTS5 and a rebuildable local
character-gram vector cache. Episodic task summaries expire after 30 days;
working records expire after 7 days. Semantic, procedural, and preference
records remain until the owner deletes them. Memory can be inspected, corrected,
exported, and deleted through the authenticated API. Search combines keyword and
vector similarity; the vectors provide fuzzy lexical recall, not neural semantic
embeddings. Relevant memories join the bounded context for larger read workflows.

The GitHub workflow now records the exact version of its notification priority
skill. A successful run containing a security alert can propose a learned,
read-only priority procedure. It is checked against synthetic fixtures and stays
inactive until the owner activates it. Activating an earlier version rolls back
the behavior. Skills are declarative data stored in SQLite and exported as
private versioned `SKILL.md` files; Orin never executes their text. The owner can
also propose a custom priority order and record corrections to completed tasks.
The same registry also versions a cross-source briefing order. A correction to a
completed briefing such as “calendar first” can propose a validated ordering
change for explicit owner activation and rollback. These are narrow,
declarative learning loops, not general autonomous skill synthesis.
Saved source orders can name a subset; future sources appear after those entries.

Read-only Gmail headers, Drive file metadata, Calendar events, and GitHub
notifications now use a shared evidence contract and task path. “Daily briefing”
combines configured sources, marks missing sources, and continues when one
provider fails. Items rotate across sources so one busy inbox does not crowd
out the others. Direct requests such as “show my unread Gmail inbox”, “recent
Drive files”, and “upcoming Calendar events” use the corresponding adapter.
Google adapters use real read endpoints and were verified with a live Google
account on 2026-11-25. See
[integration research and roadmap](INTEGRATIONS.md) for scope choices, useful
cross-service workflows, and next connector work.

Phase 4 adds durable incremental metadata sync for Gmail, Drive, and Calendar;
owner-scoped search with citations, account labels, fetch time, and an explicit
content gate; and read-only meeting preparation and follow-up queues. The
Notion, Todoist, Slack, and Microsoft Graph read adapters have credential-free
provider tests but have not been checked against live accounts. Account labels
for Calendar and these optional sources are caller configured and shown as
`unverified` unless configured. Search indexes metadata from connected reads;
local `.md` and `.txt` content is indexed only from an approved root and returned
only with the `search.content` grant.

The local API now supports owner-scoped capability grants, exact single-use
approvals, audited local tools, and a trusted stdio MCP registry. Filesystem
writes create new files only. Terminal commands run in a bounded, networkless,
read-only Docker container with an approved workspace mount; Docker must be
available locally. Browser reads use a temporary Chrome profile and accept
public HTTPS URLs with bounded output and time. The browser profile is isolated
from the user's normal profile, but this is not a network sandbox and redirects
or DNS changes can still matter. A trusted MCP executable runs with the local
user's host privileges, so register only executables you trust; returned text
is marked untrusted data.

Scheduled one-time and daily jobs run through the same runtime with IANA time
zones, missed-run rules, leases, cancellation, and stable idempotency keys.
Delegated child tasks keep the shared task path and are limited by declared read
capabilities and model-call/token budgets. Narrow Gmail send, Calendar event
create, and Drive folder create actions require an owner grant, a matching
single-use approval, and an idempotency key. Unknown provider outcomes stop
automatic retries; Calendar and Drive can be reconciled with read requests.
Gmail send with an unknown outcome requires manual inspection of Sent mail.
These write paths have provider-shaped tests; no real Google write was sent.

Phase 5A adds a local browser control center built from a static Next.js export.
The existing FastAPI process serves both the UI and API at `127.0.0.1`; the
browser uses a one-time terminal pairing code, an HttpOnly session cookie, and
CSRF protection. It shows tasks, results, model usage and health, configured
sources, exact approval requests, and schedules. The configuration label means
local credential and owner grant are present, not that a provider was just
contacted. Tauri packaging and deeper memory/skill management remain in 5B.

The GitHub notifications endpoint currently requires a classic personal access
token with the `notifications` scope. GitHub does not support fine-grained tokens
for this endpoint. Orin makes GET requests only and limits this capability to
users named in `ORIN_GITHUB_ALLOWED_USERS`. The token itself has broader GitHub
permissions than this runtime uses. Keep it in the environment or ignored `.env`
file. [GitHub notifications API](https://docs.github.com/en/rest/activity/notifications)

### Setup

Install Python 3.14 and uv, then run `uv sync`. Set values in the ignored `.env`
file or your environment:

```dotenv
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_USER_IDS=123456789
OPENROUTER_API_KEY=sk-or-...
GITHUB_TOKEN=your-classic-token-with-notifications-scope
ORIN_GITHUB_ALLOWED_USERS=123456789,local
ORIN_API_TOKEN=choose-a-long-random-token
ORIN_API_USER=local
# ORIN_MODEL=openrouter:nvidia/nemotron-3.5-lightning:free
# ORIN_FALLBACK_MODEL=ollama:qwen2.5:0.5b
# ORIN_DATABASE_PATH=/path/to/orin.db
# ORIN_CONTEXT_TOKENS=4096
# ORIN_OUTPUT_RESERVE=512
# ORIN_TASK_MODEL_CALLS=3
# ORIN_TASK_MODEL_TOKENS=6000
ORIN_GMAIL_ALLOWED_USERS=local
ORIN_DRIVE_ALLOWED_USERS=local
ORIN_CALENDAR_ALLOWED_USERS=local
# Optional read adapters (each also needs ORIN_<SOURCE>_ALLOWED_USERS=local):
# ORIN_NOTION_TOKEN=...
# ORIN_TODOIST_TOKEN=...
# ORIN_SLACK_TOKEN=...
# ORIN_SLACK_CHANNEL_IDS=C0123456789
# ORIN_MICROSOFT_TOKEN=...
# ORIN_<SOURCE>_ACCOUNT_ID=your-account-label
# ORIN_GOOGLE_CLIENT_FILE=~/.orion/config/google_oauth_client.json
```

Set `ORIN_GITHUB_ALLOWED_USERS` to the Telegram ID or CLI/API owner that may use
the GitHub account. It defaults to `local` when unset. The API token grants access
only to `ORIN_API_USER`, which defaults to `local`. The CLI owner is `local` by
default and can be changed with `ORIN_CLI_USER`. The default database is
`~/.orion/database/orin.db`; checkpoints are in a companion SQLite file.
For Google, create a desktop OAuth client in a Google Cloud project with the
Gmail, Drive, and Calendar APIs enabled. Configure an External testing consent
screen, add your account as a test user, and add only the scopes listed in
[INTEGRATIONS.md](INTEGRATIONS.md). Save the downloaded client JSON outside the
repository at `~/.orion/config/google_oauth_client.json` with mode `0600`. Run
each command and complete consent in your browser:

```bash
uv run python -m orchestration.google_oauth gmail
uv run python -m orchestration.google_oauth drive
uv run python -m orchestration.google_oauth calendar
```

The commands use loopback OAuth with PKCE, keep each refresh token in the OS
credential store, and refresh access tokens when Orin reads a source. Set each
`ORIN_*_ALLOWED_USERS` owner grant separately. `--open-browser` opens the consent
URL automatically. `--disconnect` removes a local source credential;
`--disconnect --revoke-google` also revokes the Google grant and clears all Orin
Google source credentials for that account, because Google revocation applies to
the whole project. A direct read request without its connection pauses.
If you choose to enable a write capability, first add its scope to the consent
screen and connect it separately using the OAuth command with source
`gmail_send`, `calendar_write`, or `drive_write`. For example:

```bash
uv run python -m orchestration.google_oauth calendar_write
```

The respective scopes are
`gmail.send`, `calendar.events`, and `drive.file`. Review the exact action and
approval through the local API before running it. The existing read OAuth
connections do not authorize writes.
Short-lived `ORIN_GMAIL_ACCESS_TOKEN`, `ORIN_DRIVE_ACCESS_TOKEN`, and
`ORIN_CALENDAR_ACCESS_TOKEN` remain available as explicit environment overrides.
In Google's External **Testing** status, these refresh tokens expire after seven
days; rerun the connect commands when they expire. [Google OAuth token behavior](https://developers.google.com/identity/protocols/oauth2)

### Run

```bash
uv run main.py
uv run python -m orchestration.cli "Summarize my GitHub notifications"
uv run python -m orchestration.cli "Daily briefing"
uv run uvicorn orchestration.api:app --host 127.0.0.1
```

To use the local control center, build its static assets once and start the
single Python server. Node.js is needed for the build, not to serve the UI:

```bash
cd web
npm ci
npm run build
cd ..
uv run python -m orchestration.control_center
```

Open the printed `http://127.0.0.1:8000` URL and enter the one-time pairing
code shown in the same terminal. The browser session expires after 12 hours or
on sign-out. Restart the local server to issue a new pairing code. The UI and
API stay on the same loopback origin; no hosted Next.js service is used.
Set `ORIN_API_USER` to choose the owner (default `local`). The API bearer token
is for scripts and other clients and is never included in the web build.

The CLI supports `--session NAME` and `--resume TASK_ID`. Telegram supports
`/start`, `/status TASK_ID`, and `/resume TASK_ID`. Submit an API task with `POST /tasks`, run or
resume it with `POST /tasks/{id}/run`, inspect it with `GET /tasks/{id}`, and
stream events with `GET /tasks/{id}/events?after=EVENT_ID`. The API also exposes
`GET /tasks`, `GET /tasks/{id}/usage`, `GET /models`, `GET /capabilities`, `GET /sessions`, and
`GET /sessions/{id}/messages`. Send
`Authorization: Bearer <ORIN_API_TOKEN>` and `X-Orin-User: <ORIN_API_USER>`
headers. The API token is required for programmatic task and control routes;
the paired browser uses its owner-scoped session instead. Bind the server to localhost.

Phase 4 routes include `POST /sync/{gmail|drive|calendar}` with an account ID,
`GET /search` and `POST /search/index-local`; `/policy/grants`, `/policy/roots`,
`/policy/audit`, and `/approvals`; `/actions` for preparing, running, and
reconciling writes; `/schedules` and `/delegations`; `/tools/files`,
`/tools/terminal`, `/tools/browser`, and `/mcp/servers`. All use the same API
token and owner header. A running schedule needs a separate local worker:

```bash
uv run python -m orchestration.schedule_worker
```

Use `--once` to dispatch due jobs once. Keep this worker running for daily jobs.
Schedule requests can perform any already authorized read workflow, so review
the request and connected sources before creating one. All Phase 4 API routes
are local controls; no Telegram approval interface exists yet.

Memory routes are `POST/GET /memories`, `GET /memories/search?q=...`,
`GET /memories/export`, and `GET/PUT/DELETE /memories/{id}`. Skill routes are
`GET /skills`, `GET /skills/metrics`, `POST /skills/custom`, `POST /skills/briefing`,
`GET /skills/{id}`, and `POST /skills/{id}/activate`. Use
`GET /tasks/{id}/skill` to inspect attribution and
`POST /tasks/{id}/corrections` to record feedback. Activation is the explicit
owner review step. The API token and owner header apply to these routes for
programmatic clients; the paired browser session also authorizes same-origin
requests.

A task paused by a provider or capability failure can be resumed by ID. Work
already checkpointed by LangGraph is reused. An interrupted process leaves a
running task recoverable once its worker process is gone. Cancellation currently
applies to pending and paused tasks. Duplicate Telegram message IDs and API
idempotency keys reuse the original task.

### Verify

```bash
uv run python -m pytest -q
cd web
npm run typecheck
npm test
npm run format:check
npm run build
```

The suite simulates Telegram, HTTP, CLI, GitHub API responses, and process
interruption without live credentials. On 2026-11-25, a live GitHub notifications
request completed and the Telegram bot returned its result through the same
runtime. Phase 2 also passed a live synthetic five-item summary using OpenRouter,
and a structured classifier call using local Ollama. These live checks were run
separately from the automated suite. Run the versioned, credential-free comparison
with `uv run python -m evaluation.benchmark`. Its token counts are scripted
fixture values and its latency measures local execution. See
[evaluation/README.md](evaluation/README.md) for a reproducible demo.
Run `uv run python -m evaluation.learning` for a credential-free Phase 3 demo:
one GitHub task proposes a skill, activation makes a crowded security alert
visible, and rollback restores the prior ordering. It also measures three
synthetic memory-retrieval queries. No provider call is needed for this demo.
The integration suite mocks provider HTTP to test Gmail, Drive, and Calendar
requests and runs a cross-source briefing through checkpointing, artifacts,
memory, correction, activation, and rollback. OAuth tests cover scope selection,
PKCE, owner separation, refresh, state rejection, and revocation. Separately, a
read-only live check on 2026-11-25 fetched Gmail headers, Drive metadata, and
Calendar events, then completed a four-source briefing through the shared
runtime with model calls disabled. The check printed statuses and item counts,
not private source contents.
On 2026-11-25, a separate live Telegram check connected the same three
read-only Google scopes to the authorized Telegram owner through desktop OAuth.
Messages requesting the Gmail inbox, recent Drive files, upcoming Calendar
events, and a daily briefing all completed and received bot replies. The
briefing's execution history recorded completed Gmail, Drive, Calendar, and
GitHub reads. The local bot process was stopped after this smoke check; start it
with `uv run main.py` to receive new Telegram messages.
The Phase 4 fictional Aurora launch test exercises meeting prep, cited search,
approved local content, a scheduled briefing, bounded delegation, and an
ambiguous Calendar write across the API and runtime. Provider-shaped tests
check Google write request bodies and single-use approval behavior. The
credential-free search evaluation runs with
`uv run python -m evaluation.phase4_search`; its fixture spans Gmail, Drive,
Calendar, and one approved local note.
The Phase 5A browser check used an isolated database and the exported UI served
by FastAPI: pairing, task creation and reload, approval review, daily schedule
save/cancel, source and model views, and sign-out passed. A second isolated
browser run completed a real read-only Calendar request and recorded a
successful `calendar.events.read` execution without exposing event contents.

## How it works today

| File | Responsibility |
|---|---|
| `main.py` | Telegram startup and handlers |
| `orchestration/bot.py` | Telegram authorization and shared-runtime adapter |
| `orchestration/cli.py` | Local CLI |
| `orchestration/api.py` | Authenticated local HTTP and event stream |
| `orchestration/control_center.py`, `orchestration/web_auth.py`, `orchestration/web_assets.py` | Local UI launcher, browser pairing, static export serving |
| `web/app`, `web/components`, `web/lib` | Next.js control center, views, and typed API client |
| `orchestration/runtime.py` | Durable execution and checkpoint recovery |
| `orchestration/store.py` | Versioned SQLite schema and task records |
| `orchestration/github.py` | Read-only GitHub notification fetch and summary |
| `orchestration/integrations.py` | Shared read evidence and Gmail, Drive, Calendar adapters |
| `orchestration/google_oauth.py` | Desktop OAuth, refresh, OS credential storage, and disconnect |
| `orchestration/sync.py`, `orchestration/search.py` | Incremental metadata sync and owner-scoped search |
| `orchestration/policy.py`, `orchestration/actions.py` | Capability grants, approvals, audit, and durable external writes |
| `orchestration/local_tools.py`, `orchestration/mcp_registry.py` | Scoped local tools and trusted stdio MCP calls |
| `orchestration/scheduler.py`, `orchestration/delegation.py` | Durable schedules and bounded child tasks |
| `orchestration/productivity.py`, `orchestration/external_reads.py` | Meeting/follow-up procedures and optional read adapters |
| `orchestration/graph.py` | Phase 0 mock graph |
| `orchestration/agents.py` | Model backend contract and structured calls |
| `orchestration/context.py` | Bounded context and private tool artifacts |
| `orchestration/model_budget.py` | Model routing, health, and task budgets |
| `orchestration/memory.py` | Owner-scoped memory, FTS5, and local vector recall |
| `orchestration/skills.py` | Declarative, versioned skills and evaluation |
| `evaluation/` | Versioned fixtures and comparison benchmark |
| `INTEGRATIONS.md` | Research, use cases, scope decisions, and connector roadmap |

---

## Target architecture

```text
Next.js / Tauri desktop        Telegram · Discord · Slack · CLI
          │                                   │
          └──────────────┬────────────────────┘
                         ▼
                  FastAPI Gateway
        auth · sessions · streaming · events · permissions
                         ▼
                  Orin Agent Runtime
   planner · executor · memory · learning · model router
   context engine · delegation · policy · budget controller
                         ▼
                     LangGraph
        durable state · checkpoints · recovery · routing
                         ▼
   filesystem · terminal · browser · MCP · APIs · scheduler
                         ▼
   free cloud models + local models (Ollama / llama.cpp)
                         ▼
   SQLite · FTS5 · vector index · skills · artifacts
```

For availability beyond a single laptop, the design adds:

- **Orin Hub** — always-on coordinator (self-hosted VPS first): channel gateway,
  task queue, cloud integrations, scheduler, inference routing.
- **Orin Node** — local execution daemon: filesystem, terminal, browser, local
  models, private files.
- **Capability-aware routing** — work goes where it can actually run; tasks wait
  in a queue if a required Node is offline.
- **One shared runtime** — Hub and Node are deployment profiles, not forks.

### Context is engineered, not dumped

| Layer | Purpose |
|---|---|
| L0 Active | Current objective, next action, key observations |
| L1 Working | Plan, progress, decisions, open questions |
| L2 Persistent | Preferences, facts, past experiences, lessons |
| L3 Procedural | Versioned skills and workflows |
| L4 Archived | Full transcripts, raw tool output, artifacts |

The runtime sends only what the current step needs, compresses large tool
outputs, and keeps a reserve for model output. Provider quotas, token budgets,
and task complexity determine how much reasoning a task is allowed to spend.

### Learning loop

```
experience → analysis → skill proposal → sandbox validation →
approval (when needed) → versioned skill → rollback available
```

---

## Roadmap

Phase 5 starts with a local web release: Next.js builds static files, and the
existing FastAPI service serves the UI and API on one loopback origin. Each
installation keeps its own local data and browser session. Tauri will package
that same UI and manage the Python service in a later Phase 5 step; it will not
create a second runtime. See [Phase 5 tasks](TODO.md#phase-5--build-the-control-center).

| Phase | Focus |
|---|---|
| **0. Prototype** ✅ | Telegram + LangGraph classify/verify demo |
| **1. Foundation** ✅ | Local API, shared runtime, provider contract, capability registry, SQLite, sessions, event streaming |
| **2. Context engineering** ✅ | Token budgeting, bounded context, retrieval, model health, fallback routing, evaluation |
| **3. Adaptive learning** ✅ | Owner-scoped memory, GitHub priority skill proposals/versioning, evaluator, rollback |
| **4. Autonomy** ✅ core | Sync/search, scoped tools, MCP, bounded delegation, scheduler, approvals, narrow writes; live optional-account checks pending |
| **5. Interfaces** ✅ 5A | Local Next.js static control center complete; Tauri packaging and deeper management views remain |
| **6. Hardening** | Benchmarks, recovery/security tests, migrations, backup, installer |
| **7. Distributed** | Hub, Node, capability routing, selective encrypted sync |

The recommended MVP: a solid Python runtime with Telegram + CLI, GitHub/Gmail/
Drive/Calendar reads, then Notion/filesystem/terminal tools, persistent memory,
skill retrieval, budget
control, approvals, and scheduled tasks — **before** building the full desktop
experience.

---

## Design principles

1. **Provider independence** — no dependence on one vendor's tool-calling quirks.
2. **Context independence** — resume from local state, not a giant transcript.
3. **Real learning** — reusable procedures, not just saved conversations.
4. **Graceful degradation** — switch models or simplify strategy, and know when
   to pause.
5. **Local ownership** — exportable data, skills, memory, and history.
6. **Human control** — explicit permission scopes and approval for destructive
   actions.

### Security notes

- A connected account does not mean unrestricted access; grant read/write scopes
  independently.
- Treat web pages, documents, and MCP output as **data**, never as instructions.
- Secrets belong in the OS credential store, not plaintext configuration.
- Never commit `.env` or bot tokens.
- Set `TELEGRAM_ALLOWED_USER_IDS` before starting the bot.

---

## Documentation

- [`AGENTS.md`](AGENTS.md) — complete project context, architecture, current
  state, known issues, conventions, and the recommended next tasks. **Read this
  before contributing.**
- Original design discussion:
  [shared ChatGPT conversation](https://chatgpt.com/share/6af154ff-b0f4-83ee-ae1f-6e5124841dca)

---

## Naming

The repository, bot, and package use **Orin**. **ORION** is the name from the original design discussion.

---

## License

No license has been declared yet.
