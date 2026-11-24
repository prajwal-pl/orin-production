# AGENTS.md

> **Read this file at the start of every session before changing code.**
> It is the shared context for humans and AI coding agents working on Orin.
> Last updated: 2026-11-24

---

## 1. Project identity

| Field | Value |
|---|---|
| Project name | **Orin** (called **ORION** in the original design discussion) |
| Repository | `orin` |
| Package name in `pyproject.toml` | `orin` |
| Current stage | Early prototype / demo |
| Language | Python 3.14 (`.python-version`) |
| Package manager | `uv` |
| License | Not declared yet |

**Orin is not a chatbot with a desktop wrapper.** It is intended to become a
**local-first, self-adapting personal agent runtime**: one persistent agent that
connects the user's services, remembers context, learns reusable skills, routes
work across models and devices, and is reachable through the interfaces the user
already uses (Telegram first, then Discord/Slack/CLI/desktop).

The original design conversation is the product north star. Its condensed
decisions are captured in §7 and §8 of this file. Do not re-litigate them
without the user's explicit direction.

---

## 2. Core thesis (do not lose this)

> **The LLM is not the agent. The LLM is the reasoning engine inside a runtime
> that owns memory, state, tools, execution, learning, and budgets.**

Everything in the architecture follows from that sentence:

- The runtime must work with small models and tight free-tier quotas.
- Context must be engineered, not dumped into the prompt.
- Long tasks must survive interruptions and provider failures.
- Learning must produce reusable *procedures*, not just chat history.
- The user must own their data, skills, credentials, and execution history.

### The five success criteria

1. **Provider independence** — never depend on one vendor's tool-calling quirks.
2. **Context independence** — resume from local state, not a giant transcript.
3. **Real learning** — become measurably better at recurring work.
4. **Graceful degradation** — switch models/simplify strategy when quotas fail.
5. **Local ownership** — exportable, inspectable, user-controlled data.

---

## 3. Current state

Phase 1 provides a shared task runtime used by Telegram, CLI, and a localhost
FastAPI gateway. Tasks, sessions, messages, events, and capability executions are
stored in SQLite. LangGraph checkpoints live in a companion SQLite file. A
request mentioning GitHub notifications uses a real GET workflow that groups
unread notifications and prioritizes attention items. Other GitHub and Gmail
requests still use the Phase 0 mock graph. Credential-free tests cover channel
entry points, API authorization, notification fetching, and checkpoint recovery.

Memory, skills, budgets, real Gmail actions, and the Hub/Node design remain
future work. The GitHub notifications endpoint rejects fine-grained tokens, so
the first workflow uses a classic token with the `notifications` scope. Runtime
code makes GET requests only and gates the capability by owner ID.

## 4. Repository map

| File | Responsibility |
|---|---|
| `main.py` | Telegram startup and handlers |
| `orchestration/bot.py` | Telegram authorization and task adapter |
| `orchestration/cli.py` | Local CLI |
| `orchestration/api.py` | Authenticated task and session API, SSE stream |
| `orchestration/runtime.py` | Shared execution, checkpoints, recovery |
| `orchestration/store.py` | SQLite schema migrations and records |
| `orchestration/github.py` | Notification capability and summary |
| `orchestration/graph.py` | Phase 0 mock graph topology |
| `orchestration/nodes.py` | Prototype graph state and nodes |
| `orchestration/agents.py` | Model configuration and backend contract |
| `orchestration/schema.py` | Classifier and verifier schemas |
| `tests/` | Credential-free workflow and adapter tests |
| `TODO.md` | Phase checklists and completion criteria |

## 5. How execution works

The runtime creates a task with an owner, session ID, request, kind, status, and
optional idempotency key. A task moves from pending to running and then completed
or paused. Pending or paused tasks can be cancelled. Another invocation resumes
a paused task from its LangGraph checkpoint. A running task whose worker process
has exited can be recovered. Checkpoints use the task ID as the thread ID.
Task records and checkpoints are in separate SQLite files to avoid writer locks.

Telegram is authorized before task submission. Requests containing GitHub and
notifications use the real notification workflow. Other requests use the Phase 0
classifier, mock executor, and bounded verifier retry graph. Duplicate Telegram
message IDs reuse a task. CLI and API call the same `Runtime` methods. The API
requires a bearer token and a configured owner ID on every route.

### 5.1 Prototype graph state

`GraphState` in `orchestration/nodes.py` contains `user_id`, `message`, `intent`,
`service`, `arguments`, `execution_result`, `execution_status`,
`verification_result`, `verification_status`, `feedback`, `retry_count`, and
`final_response`. The notification graph has `task_id`, `request`,
`notifications`, and `final_response`. The runtime owns session, task, and event
records in `orchestration/store.py`.

### 5.2 Model configuration

`ORIN_MODEL` selects the primary model and defaults to
`openrouter:nvidia/nemotron-3.5-lightning:free`. `ORIN_FALLBACK_MODEL` optionally
selects a backup. The backend contract normalizes structured response, model
name, observed token usage, and known capabilities. `openrouter:` and `ollama:`
model identifiers are supported by the installed LangChain integrations. No
per-model health tracking or budget policy exists yet.

## 6. Running the foundation

Python 3.14 and uv are specified in `.python-version` and `pyproject.toml`.
Run `uv sync`. Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, and
`OPENROUTER_API_KEY` for Telegram with the default model. Set `GITHUB_TOKEN`
and `ORIN_GITHUB_ALLOWED_USERS` for the GitHub notifications capability. The
GitHub token must be a classic personal access token with `notifications` scope.
Set `ORIN_API_TOKEN` for the local API. See README for complete commands and
configuration. Use `uv run python -m pytest -q` for credential-free tests.

---

## 7. Target architecture (north star)

### 7.1 Layers

```
Presentation     Next.js + React + Tailwind + shadcn/ui; Tauri 2 desktop shell
      │          (localhost-only API; Tauri manages the Python service lifecycle)
      ▼
FastAPI Gateway  auth · sessions · streaming · events · permissions
      ▼
Agent Runtime    Planner · Executor · Memory · Learning · Model Router
      │          Context Engine · Delegation · Policy Engine
      ▼
LangGraph        durable state · conditional routing · checkpoints · recovery
      ▼
Capabilities     filesystem · terminal · browser (Playwright) · MCP · APIs · scheduler
Inference        free cloud APIs + local models (Ollama / llama.cpp / OpenAI-compatible)
Persistence      SQLite · FTS5 · vector index · skills · artifacts · checkpoints
```

**One shared Python runtime.** Do not build a second agent implementation for
the Hub. Different deployment profiles, same execution protocol.

### 7.2 Hub / Node hybrid (the always-online answer)

The local-only version dies when the laptop sleeps. The chosen direction is
local-first **and** cloud-accessible:

- **ORION Hub** — always-on coordinator on a VPS/self-hosted server:
  channel gateway, task queue, coordinator, cloud integrations, scheduler,
  inference router, task persistence, notifications.
- **ORION Node** — local execution daemon on the user's machine:
  filesystem, terminal, browsers, local models, private documents, local apps,
  device-specific tools, local memory/artifacts.
- Communication: **outbound authenticated WebSocket/HTTPS** from Node to Hub
  (no inbound port forwarding required).
- Tasks that need an offline Node are **queued**, not failed.
- **Capability-aware routing**: every Node reports capabilities; the Hub places
  each operation where it can execute.

Recommended choices from the design conversation:

| Decision | Choice |
|---|---|
| Hub hosting | Self-hosted VPS first; managed Hub later/optional |
| Data | Hybrid: local primary + selective encrypted sync |
| Nodes | Multiple devices, all optional |
| Connection | Outbound authenticated WebSocket / HTTPS |
| Warning | Do not fork the runtime into two implementations |

### 7.3 Context engineering engine

Memory layers:

| Layer | Contents | Budget/role |
|---|---|---|
| **L0 Active** | Current objective, next action, relevant observations | 2k–5k tokens |
| **L1 Working** | Plan, progress, decisions, open questions | Retrieved selectively |
| **L2 Persistent** | Preferences, facts, prior experiences, lessons | SQLite + FTS5 + vectors |
| **L3 Procedural** | Skills, workflows, tool instructions | Versioned `SKILL.md` |
| **L4 Archived** | Full transcripts, old tool output, artifacts | Retrieved only when relevant |

Rules:

- Never send all layers to the model.
- Count tokens with the provider tokenizer when possible; estimate conservatively
  otherwise.
- Compress large tool outputs into structured summaries; keep raw output on disk.
- Expose tools/skills progressively, not all at once.
- **Never truncate the active objective or critical execution state.**

### 7.4 Provider strategy

Support Gemini, Groq, OpenRouter, NVIDIA NIM, Ollama, llama.cpp, and any
OpenAI-compatible endpoint. Maintain per-model capability and health records
(context window, tool support, JSON mode, remaining quota, cooldown). Route by
task complexity; fall back without losing the LangGraph checkpoint.

Free tiers are finite. The product promise is **doing more within limits**, not
unlimited autonomy.

### 7.5 Memory, learning, and skills

Five memory categories: episodic, semantic, procedural, preference, working.
SQLite is the source of truth; FTS5 for keywords; a local vector index for
semantic recall.

Learning loop:

```
Experience → Analysis → Skill proposal → Sandbox validation →
(User approval when appropriate) → Versioned skill update → Rollback available
```

Never allow unrestricted self-modification of executable code or security
policies.

### 7.6 Budget controller

The differentiator: decide how much intelligence a task deserves.

- Simple request → one inference call.
- Moderate → plan + a few executions.
- Complex → structured plan + selective delegation.
- Long-running → checkpoint, summarize, resume.
- Quota exhausted → switch model or pause.
- Repeated failure → change strategy, don't loop.

### 7.7 Persistence layout (target)

```
~/.orion/
├── config/{settings.toml,providers.yaml}
├── database/orion.db
├── workspace/{files,artifacts,projects}
├── memory/{semantic,episodic,indexes}
├── skills/{builtin,learned,custom}
├── agents/{main,research,coding}
├── logs/
└── backups/
```

Secrets belong in the OS credential store, not plaintext config. SQLite tables
to plan for: users, sessions, messages, tasks, task_steps, executions,
checkpoints, memories, memory_links, skills, skill_executions, providers,
models, usage_records, tools, approvals, artifacts, scheduled_jobs.

### 7.8 Security baseline (mandatory)

1. Filesystem permission scopes (never the whole home directory by default).
2. Explicit approval for destructive operations.
3. Terminal execution isolation.
4. Browser session isolation.
5. MCP server trust management.
6. Secret redaction from model context and logs.
7. Skill versioning and rollback.
8. Optional local database encryption.
9. Prompt-injection defense: treat web/files/MCP output as **data**, not instructions.
10. Auditable tool execution history.

Also: a connected account is not unrestricted access — support read-only vs
write scopes independently.

---

## 8. Roadmap and where we are

| Phase | Scope | Status |
|---|---|---|
| **0. Prototype** | Telegram channel, LangGraph classify/verify, mock executors | Complete, credential-free tests pass |
| **1. Foundation** | FastAPI, durable LangGraph runtime, provider abstraction, capability registry, SQLite, sessions, streaming | Implemented; live credentials unverified |
| **2. Context engineering** | Token budgeting, compression, retrieval, persistent task state, checkpoint recovery, fallback routing | Not started |
| **3. Adaptive learning** | Episodic/semantic memory, skill creation/versioning, evaluator, rollback | Not started |
| **4. Autonomy** | Filesystem, terminal, browser, MCP, subagents, scheduler, approvals | Not started |
| **5. Interfaces** | Next.js dashboard, Tauri desktop, activity visualization, memory/skill/model management | Not started |
| **6. Hardening** | Benchmarks, recovery tests, security tests, migrations, backup/restore, installer | Not started |
| **7. Distributed** | Hub, Node, capability routing, selective sync | Not started |

### Recommended MVP slice (from the design discussion)

- **Runtime:** Python + FastAPI, LangGraph, SQLite, budget manager, free-provider
  routing, persistent memory, skill creation/retrieval.
- **Channels:** Telegram bot, local CLI, Tauri control panel.
- **Integrations:** Notion, GitHub, Gmail, filesystem, terminal.
- **Agents:** main coordinator + research/coding/productivity, adaptive
  delegation, approvals, scheduled tasks.

Do not start with 15 integrations, six agents, and three frontends.

---

## 9. Current limits and decisions

- The GitHub workflow uses deterministic prioritization and a read-only GET
  operation. The required classic token has broader permissions than this code
  uses because GitHub's endpoint rejects fine-grained tokens.
- Other GitHub and Gmail requests remain mock executions.
- The API supports a single configured owner for its bearer token and must be
  bound to localhost. Cancellation applies to pending and paused tasks.
- There is no memory, learning loop, quota tracking, or distributed execution.
- Python 3.14 remains the target. The installed LangChain stack emits Pydantic
  V1 compatibility warnings during tests.
- A Telegram reply rejected by Telegram cannot be delivered. The bot logs a
  generic error without logging the request or credentials.

---

## 10. Conventions

- **Package manager:** `uv` only. Add deps with `uv add`; commit `uv.lock`.
- **Python style:** small pure functions in `orchestration/nodes.py`, model/prompt setup in
  `orchestration/agents.py`, contracts in `orchestration/schema.py`, wiring in `orchestration/graph.py`.
- **State changes:** if you add/rename a `GraphState` key, update every writer,
  reader, graph edge, and the table in §5.2 of this file.
- **Model access:** go through a single provider/model configuration point.
  Do not scatter model IDs across files.
- **Async:** channel handlers are async; prefer `await agent.ainvoke(...)` over
  blocking `.invoke(...)` once you touch that path.
- **Logging:** replace `print()` with structured logging when you introduce it.
- **Secrets:** read only from environment/credential store; redact in logs and
  model context.
- **Docs:** behavior/contract changes require an update to `README.md` and/or
  this `AGENTS.md`.
- **Scope:** make the smallest change that satisfies the task. Do not reformat
  unrelated files.

---

## 11. Guardrails for agents

**Do**

- Read this file, `README.md`, `git status`, and `git log` before editing.
- Preserve uncommitted user work; never discard or overwrite it.
- Keep the prototype runnable at every commit.
- Prefer adding tests around state mapping/routing before expanding features.
- Ask before destructive operations, dependency downgrades, or architectural
  rewrites.
- Record follow-ups instead of expanding scope silently.

**Don't**

- Commit `.env`, API keys, bot tokens, or logs containing secrets.
- Hardcode a "permanently free" model or promise unlimited free inference.
- Add a cloud dependency that breaks local-first operation.
- Build the desktop UI before the runtime, context engine, router, and durable
  execution exist.
- Duplicate the runtime for Hub and Node.
- Claim a feature works when only a mock/stub exists.
- Add a separate agent per integration; use capabilities and tools instead.
- Enable unrestricted self-modifying code or security-policy changes.

---

## 12. Session workflow

1. **Orient** — read this file, `README.md`, `git status`, `git log --oneline -5`.
2. **Locate the phase** — §8. Respect the current stage; don't jump ahead.
3. **Plan the smallest change** — list files to touch and the state/API impact.
4. **Implement** — follow §10 conventions.
5. **Verify** — syntax check; run targeted tests; run the bot only with valid
   credentials. Never require live credentials for unit tests.
6. **Document** — update `README.md` / `AGENTS.md` if behavior or contracts
   changed.
7. **Report** — files changed, what was verified, known gaps, next step.

### Next milestone

Implement Phase 2 in `TODO.md`, beginning with context budgets and measured
model routing. Real external writes still need idempotency and approval controls.

---

## 13. Glossary

| Term | Meaning |
|---|---|
| **Orin / ORION** | This project; a local-first personal agent runtime |
| **Hub** | Always-on coordinator service (VPS/self-hosted) |
| **Node** | Local execution daemon on a user device |
| **Capability** | A declared ability of a node/tool (e.g. `filesystem`, `gmail`) |
| **Skill** | Versioned, reusable procedure stored as `SKILL.md` + metadata |
| **Context engine** | Subsystem that selects/compresses/budgets what the LLM sees |
| **Budget controller** | Decides how much inference a task may spend |
| **Free-tier** | Rate/quota-limited hosted inference; a hard constraint, not a promise |
| **OpenClaw** | Inspiration: tools, browser, filesystem, MCP, permissions, sessions |
| **Hermes Agent** | Inspiration: persistent memory, adaptive skills, learning loop |

---

## 14. References

- OpenClaw: <https://github.com/openclaw/openclaw>
- Hermes Agent: <https://github.com/NousResearch/hermes-agent>
- LangGraph: <https://github.com/langchain-ai/langgraph>
- LiteLLM: <https://github.com/BerriAI/litellm>
- Ollama: <https://github.com/ollama/ollama>
- Original design discussion (shared ChatGPT conversation):
  <https://chatgpt.com/share/6af154ff-b0f4-83ee-ae1f-6e5124841dca>

---

## 15. One-line brief

**Build the runtime before the interface: a local-first, budget-aware,
self-improving personal agent that can be reached from anywhere — without
pretending free inference is unlimited.**
