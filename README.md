# Orin

**A local-first, self-adapting personal agent runtime.**

Orin is being built as one persistent agent that connects the services you
already use, remembers your context, learns reusable skills, and executes tasks
across local and cloud environments — through interfaces you already use, like
Telegram, instead of yet another chat window.

> The LLM is not the agent. The LLM is the reasoning engine inside a runtime that
> owns memory, state, tools, execution, learning, and budgets.

> **Status: tested Phase 0 prototype.** This repository contains a Telegram
> + LangGraph demo with mock Gmail/GitHub actions. The runtime described below is
> the target architecture, not the current feature set. See
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

Phase 0 is a tested Telegram and LangGraph prototype. It classifies requests,
routes Gmail and GitHub requests to mock executors, verifies results, and retries
failed verification up to three total executions. Other requests receive an
explicit unsupported response. Authorized Telegram user IDs are required before
any model call. The model configuration supports an override and optional backup.

There are no real Gmail or GitHub actions, persistence, memory, skills, budgets,
FastAPI gateway, desktop UI, or Hub/Node deployment yet. See [TODO.md](TODO.md).

## Quickstart

Install Python 3.14 and uv, then run `uv sync`. Create an ignored `.env` file:

```dotenv
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_USER_IDS=123456789
OPENROUTER_API_KEY=sk-or-...
# ORIN_MODEL=openrouter:nvidia/nemotron-3.5-lightning:free
# ORIN_FALLBACK_MODEL=openrouter:your-backup-model
```

Use comma-separated numeric Telegram user IDs for multiple users. An OpenRouter
key is required when either configured model uses OpenRouter. The default model
is `openrouter:nvidia/nemotron-3.5-lightning:free`. Start the bot with
`uv run main.py` and run credential-free tests with `uv run python -m pytest -q`.
Tests simulate Telegram messages and model calls without live credentials.

## How it works today

| File | Responsibility |
|---|---|
| `main.py` | Startup validation and Telegram handlers |
| `orchestration/bot.py` | Authorization, graph calls, and replies |
| `orchestration/graph.py` | Routing and bounded retries |
| `orchestration/nodes.py` | Graph state, async nodes, mock executors |
| `orchestration/agents.py` | Central model configuration and structured calls |
| `orchestration/schema.py` | Structured output contracts |

The graph classifies, executes a mock Gmail or GitHub action, and verifies the
mock result. Recoverable verification failure re-executes the same mock node up to three total
attempts. The `other` route ends with an unsupported response. The runtime owns
the retry counter. Model and reply failures produce a generic user-facing reply.

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
| **1. Foundation** | FastAPI, durable runtime, provider abstraction, tool registry, SQLite, sessions, streaming |
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
