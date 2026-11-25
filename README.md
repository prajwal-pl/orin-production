# Orin

**A local-first, self-adapting personal agent runtime.**

Orin is being built as one persistent agent that connects the services you
already use, remembers your context, learns reusable skills, and executes tasks
across local and cloud environments — through interfaces you already use, like
Telegram, instead of yet another chat window.

> The LLM is not the agent. The LLM is the reasoning engine inside a runtime that
> owns memory, state, tools, execution, learning, and budgets.

> **Status: shared read-only workflows and versioned skills.** Telegram, CLI,
> and a local API share a SQLite-backed runtime. GitHub notifications have a
> live-tested adapter; Gmail headers, Drive metadata, and Calendar events have
> credential-dependent read adapters and synthetic end-to-end tests. See
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
Google adapters use real read endpoints but have only been exercised against
mocked HTTP responses, not a live Google account. See
[integration research and roadmap](INTEGRATIONS.md) for scope choices, useful
cross-service workflows, and next connector work.

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
# ORIN_GMAIL_ACCESS_TOKEN=short-lived-read-only-token
# ORIN_GMAIL_ALLOWED_USERS=local
# ORIN_DRIVE_ACCESS_TOKEN=short-lived-metadata-token
# ORIN_DRIVE_ALLOWED_USERS=local
# ORIN_CALENDAR_ACCESS_TOKEN=short-lived-events-token
# ORIN_CALENDAR_ALLOWED_USERS=local
```

Set `ORIN_GITHUB_ALLOWED_USERS` to the Telegram ID or CLI/API owner that may use
the GitHub account. It defaults to `local` when unset. The API token grants access
only to `ORIN_API_USER`, which defaults to `local`. The CLI owner is `local` by
default and can be changed with `ORIN_CLI_USER`. The default database is
`~/.orion/database/orin.db`; checkpoints are in a companion SQLite file.
Google tokens are optional, separate per capability, and currently supplied
manually. There is no Google OAuth consent or token refresh flow yet; use
short-lived tokens with only the documented read scopes. A direct read request
without its token pauses until that source is configured.

### Run

```bash
uv run main.py
uv run python -m orchestration.cli "Summarize my GitHub notifications"
uv run python -m orchestration.cli "Daily briefing"
uv run uvicorn orchestration.api:app --host 127.0.0.1
```

The CLI supports `--session NAME` and `--resume TASK_ID`. Telegram supports
`/start`, `/status TASK_ID`, and `/resume TASK_ID`. Submit an API task with `POST /tasks`, run or
resume it with `POST /tasks/{id}/run`, inspect it with `GET /tasks/{id}`, and
stream events with `GET /tasks/{id}/events?after=EVENT_ID`. The API also exposes
`GET /tasks`, `GET /tasks/{id}/usage`, `GET /models`, `GET /capabilities`, `GET /sessions`, and
`GET /sessions/{id}/messages`. Send
`Authorization: Bearer <ORIN_API_TOKEN>` and `X-Orin-User: <ORIN_API_USER>`
headers. The API token is required for every route. Bind the server to localhost.

Memory routes are `POST/GET /memories`, `GET /memories/search?q=...`,
`GET /memories/export`, and `GET/PUT/DELETE /memories/{id}`. Skill routes are
`GET /skills`, `GET /skills/metrics`, `POST /skills/custom`, `POST /skills/briefing`,
`GET /skills/{id}`, and `POST /skills/{id}/activate`. Use
`GET /tasks/{id}/skill` to inspect attribution and
`POST /tasks/{id}/corrections` to record feedback. Activation is the explicit
owner review step. The API token and owner header apply to every route.

A task paused by a provider or capability failure can be resumed by ID. Work
already checkpointed by LangGraph is reused. An interrupted process leaves a
running task recoverable once its worker process is gone. Cancellation currently
applies to pending and paused tasks. Duplicate Telegram message IDs and API
idempotency keys reuse the original task.

### Verify

```bash
uv run python -m pytest -q
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
The integration suite uses mocked provider HTTP to test Gmail, Drive, and
Calendar requests and runs a cross-source briefing through checkpointing,
artifacts, memory, correction, activation, and rollback. It does not prove live
Google connectivity. A separate read-only smoke check on 2026-11-25 completed
the new briefing path through the existing GitHub connection and saved one
artifact; Google sources were left unconfigured for that check.

## How it works today

| File | Responsibility |
|---|---|
| `main.py` | Telegram startup and handlers |
| `orchestration/bot.py` | Telegram authorization and shared-runtime adapter |
| `orchestration/cli.py` | Local CLI |
| `orchestration/api.py` | Authenticated local HTTP and event stream |
| `orchestration/runtime.py` | Durable execution and checkpoint recovery |
| `orchestration/store.py` | Versioned SQLite schema and task records |
| `orchestration/github.py` | Read-only GitHub notification fetch and summary |
| `orchestration/integrations.py` | Shared read evidence and Gmail, Drive, Calendar adapters |
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

| Phase | Focus |
|---|---|
| **0. Prototype** ✅ | Telegram + LangGraph classify/verify demo |
| **1. Foundation** ✅ | Local API, shared runtime, provider contract, capability registry, SQLite, sessions, event streaming |
| **2. Context engineering** ✅ | Token budgeting, bounded context, retrieval, model health, fallback routing, evaluation |
| **3. Adaptive learning** ✅ | Owner-scoped memory, GitHub priority skill proposals/versioning, evaluator, rollback |
| **4. Autonomy** | Filesystem, terminal, browser, MCP, subagents, scheduler, approvals |
| **5. Interfaces** | Next.js dashboard, Tauri desktop, activity visualization |
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
