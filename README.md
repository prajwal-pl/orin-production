# Orin

**A local-first, self-adapting personal agent runtime.**

Orin is being built as one persistent agent that connects the services you
already use, remembers your context, learns reusable skills, and executes tasks
across local and cloud environments — through interfaces you already use, like
Telegram, instead of yet another chat window.

> The LLM is not the agent. The LLM is the reasoning engine inside a runtime that
> owns memory, state, tools, execution, learning, and budgets.

> **Status: Phase 1 foundation.** Telegram, CLI, and a local API share a SQLite-backed
> task runtime. GitHub notifications use a real read-only API call. Gmail and
> other GitHub requests still use mock actions. See [Current status](#current-status).

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
summary uses deterministic rules. Other GitHub and Gmail requests still run the
Phase 0 mock graph.

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
# ORIN_FALLBACK_MODEL=ollama:llama3.2
# ORIN_DATABASE_PATH=/path/to/orin.db
```

Set `ORIN_GITHUB_ALLOWED_USERS` to the Telegram ID or CLI/API owner that may use
the GitHub account. It defaults to `local` when unset. The API token grants access
only to `ORIN_API_USER`, which defaults to `local`. The CLI owner is `local` by
default and can be changed with `ORIN_CLI_USER`. The default database is
`~/.orion/database/orin.db`; checkpoints are in a companion SQLite file.

### Run

```bash
uv run main.py
uv run python -m orchestration.cli "Summarize my GitHub notifications"
uv run uvicorn orchestration.api:app --host 127.0.0.1
```

The CLI supports `--session NAME` and `--resume TASK_ID`. Telegram supports
`/start`, `/status TASK_ID`, and `/resume TASK_ID`. Submit an API task with `POST /tasks`, run or
resume it with `POST /tasks/{id}/run`, inspect it with `GET /tasks/{id}`, and
stream events with `GET /tasks/{id}/events?after=EVENT_ID`. The API also exposes
`GET /tasks`, `GET /sessions`, and `GET /sessions/{id}/messages`. Send
`Authorization: Bearer <ORIN_API_TOKEN>` and `X-Orin-User: <ORIN_API_USER>`
headers. The API token is required for every route. Bind the server to localhost.

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
interruption without live credentials. A live GitHub or Telegram call requires
your own credentials and was not part of the automated test run.

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
| `orchestration/graph.py` | Phase 0 mock graph |
| `orchestration/agents.py` | Model backend contract and structured calls |

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
| **2. Context engineering** | Token budgeting, compression, retrieval, checkpoints, fallback routing |
| **3. Adaptive learning** | Episodic/semantic memory, skill creation/versioning, evaluator, rollback |
| **4. Autonomy** | Filesystem, terminal, browser, MCP, subagents, scheduler, approvals |
| **5. Interfaces** | Next.js dashboard, Tauri desktop, activity visualization |
| **6. Hardening** | Benchmarks, recovery/security tests, migrations, backup, installer |
| **7. Distributed** | Hub, Node, capability routing, selective encrypted sync |

The recommended MVP: a solid Python runtime with Telegram + CLI, Notion/GitHub/
Gmail/filesystem/terminal tools, persistent memory, skill retrieval, budget
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
