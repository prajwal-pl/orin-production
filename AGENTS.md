# AGENTS.md

> **Read this file at the start of every session before changing code.**
> It is the shared context for humans and AI coding agents working on Orin.
> Last updated: 2026-11-25

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

Phase 4 builds on the shared task runtime used by Telegram, CLI, and a localhost
FastAPI gateway. Tasks, sessions, messages, events, and capability executions are
stored in SQLite. LangGraph checkpoints live in a companion SQLite file. A
request mentioning GitHub notifications uses a real GET workflow that groups
unread notifications and prioritizes attention items. Gmail inbox headers,
Drive file metadata, and Calendar events use separate read-only Google adapters;
daily briefings combine available sources and report missing or failed ones.
Items rotate across sources to avoid one busy inbox hiding the rest.
Plain email read wording reaches Gmail. Recent inbox requests return up to ten
headers; sender checks scan the 50 newest unread inbox headers and disclose
when older unread mail was not checked because `gmail.metadata` forbids Gmail's
search query parameter. The combined request was live-read on 2026-11-25.
Google adapters have mocked HTTP tests and were live-authorized and read on
2026-11-25.
Other GitHub and Gmail actions still use the Phase 0 mock graph. Credential-free tests cover channel
entry points, API authorization, notification fetching, and checkpoint recovery.

Bounded context selects relevant session messages and tool excerpts while
preserving the active objective. The GitHub workflow stores normalized tool
output in a private artifact. Inboxes with at least five notifications use a
budgeted model call for suggested highlights and retain a deterministic source
list. Smaller inboxes use the local summary. Model attempts, health, token usage,
and task budget state are recorded in SQLite. OpenRouter and local Ollama calls
have been exercised live with synthetic data. A versioned, credential-free
benchmark compares scripted single-model and budget-aware routing.

Owner-scoped memory records now use SQLite, FTS5, and a rebuildable character-gram
vector cache. The cache gives fuzzy lexical recall; neural semantic embeddings
are not implemented. Completed GitHub tasks save 30-day episodes. Working
memories expire after 7 days; other categories persist until deletion. Larger
read workflows retrieve relevant memories into the bounded model context.
The GitHub workflow records its active declarative skill version. A completed
run with a security alert can propose an improved priority order, validated
against synthetic fixtures. An owner must explicitly activate it; activating
the previous version rolls back. The local API exposes owner-scoped memory
inspection, correction, export, and deletion, plus skill inspection, activation,
and usage metrics. The registry also holds a daily-briefing source-order skill;
an explicit correction such as “calendar first” can propose a new version.

Phase 4 adds incremental Google metadata sync, cited search, deterministic
meeting preparation and follow-up queues, owner-scoped policy and single-use
approvals, scoped local tools, stdio MCP trust, durable schedules, and bounded
child tasks. Narrow Gmail send, Calendar event create, and Drive folder create
actions stop on ambiguous provider responses and have provider-shaped tests.
The optional Notion, Todoist, Slack, and Microsoft Graph read adapters and
Google write scopes have not been live verified. General skill synthesis,
neural embeddings, and Hub/Node execution remain future work. The GitHub
notifications endpoint rejects fine-grained tokens, so its read workflow uses
a classic token with the `notifications` scope and makes GET requests only.

Phase 5A adds a static Next.js control center served from the same loopback
FastAPI process as the API. A terminal-issued one-time code pairs one browser
session for the configured owner; HttpOnly cookies, same-origin checks, and
CSRF guard browser writes. The UI shows tasks, results, usage, model health,
locally configured sources, approvals, and schedules. The browser flow was
tested against a local server with an isolated database. The subsequent 5B
work adds the desktop wrapper and deeper memory/skill controls.
The UI design is recorded in `web/DESIGN.md`: task-first layout, restrained
warm-neutral tokens, accessible status labels, and reduced-motion fallbacks.
The pairing screen and workbench share a saved light/dark preference that
defaults to the OS setting. The SVG favicon is part of the Next.js static
export and is served from the loopback FastAPI process.
Phase 5B adds a Tauri launcher under `desktop/`. It starts a PyInstaller-frozen
copy of the same Python service and exported UI, exposes stop/restart and the
loopback browser URL, and opens a local webview after one-time pairing. The
browser control center now manages memory and skill versions and inspects
session messages, observed usage, and successful source reads. Google OAuth
disconnect is local-only. Desktop task/approval notifications are generic and
contain no request contents. Discord and Slack channel adapters remain gated
on verified account linking and channel authorization.

## 4. Repository map

| File | Responsibility |
|---|---|
| `main.py` | Telegram startup and handlers |
| `orchestration/bot.py` | Telegram authorization and task adapter |
| `orchestration/cli.py` | Local CLI |
| `orchestration/api.py` | Authenticated task and session API, SSE stream |
| `orchestration/control_center.py`, `orchestration/web_auth.py`, `orchestration/web_assets.py` | Loopback UI launcher, browser pairing, static assets |
| `orchestration/runtime.py` | Shared execution, checkpoints, recovery |
| `orchestration/store.py` | SQLite schema migrations and records |
| `orchestration/github.py` | Notification capability and summary |
| `orchestration/integrations.py` | Read-only evidence contract and Google adapters |
| `orchestration/google_oauth.py` | Desktop OAuth, OS credential storage, refresh, disconnect |
| `orchestration/sync.py`, `orchestration/search.py` | Google metadata cursors and cited owner-scoped search |
| `orchestration/policy.py`, `orchestration/actions.py` | Grants, approvals, audit, and durable external actions |
| `orchestration/local_tools.py`, `orchestration/mcp_registry.py` | Scoped file/container/browser tools and trusted stdio MCP |
| `orchestration/scheduler.py`, `orchestration/delegation.py` | Local schedules and bounded child tasks |
| `orchestration/productivity.py`, `orchestration/external_reads.py` | Read procedures and optional source adapters |
| `orchestration/graph.py` | Phase 0 mock graph topology |
| `orchestration/nodes.py` | Prototype graph state and nodes |
| `orchestration/agents.py` | Model configuration and backend contract |
| `orchestration/context.py` | Context selection and private tool artifacts |
| `orchestration/model_budget.py` | Model health, routing, and task budgets |
| `orchestration/memory.py` | Owner-scoped memory, FTS5, vector cache, retention |
| `orchestration/skills.py` | GitHub priority skill registry and evaluation |
| `orchestration/schema.py` | Classifier and verifier schemas |
| `evaluation/` | Synthetic fixtures and comparison benchmark |
| `web/app`, `web/components`, `web/lib`, `web/styles` | Static Next.js pages, views, typed API client, and visual tokens |
| `web/DESIGN.md` | Interface decisions and research references |
| `desktop/` | Tauri launcher, bundled Python sidecar build, native package |
| `tests/` | Credential-free workflow and adapter tests |
| `TODO.md` | Phase checklists and completion criteria |
| `INTEGRATIONS.md` | Integration research and connector roadmap |

## 5. How execution works

The runtime creates a task with an owner, session ID, request, kind, status, and
optional idempotency key. A task moves from pending to running and then completed
or paused. Pending or paused tasks can be cancelled. Another invocation resumes
a paused task from its LangGraph checkpoint. A running task whose worker process
has exited can be recovered. Checkpoints use the task ID as the thread ID.
Task records and checkpoints are in separate SQLite files to avoid writer locks.

Telegram is authorized before task submission. GitHub notifications, Gmail inbox
headers, Drive metadata, Calendar events, optional source reads, meeting prep,
follow-up queues, and daily briefings use the shared
read graph. Each source has an owner grant and token setting. Daily briefings
record partial failures and proceed with available sources. Other requests use
the Phase 0 classifier, mock executor, and bounded verifier retry graph. Duplicate Telegram
message IDs reuse a task. CLI, API, and browser control center call the same
`Runtime` methods. Programmatic API clients use a bearer token and configured
owner ID; the paired browser uses a local session and CSRF token.
Phase 4 API routes retain the same owner boundary. Google sync/search state,
policy/approval state, actions, and schedules use companion SQLite files;
delegations share the task database. The local schedule worker dispatches
through `Runtime.submit` and `Runtime.run`. Google write actions require a
separate scoped OAuth credential, a grant, an exact approval, and a stable
idempotency key. Unknown outcomes are not sent again automatically.

### 5.1 Prototype graph state

`GraphState` in `orchestration/nodes.py` contains `user_id`, `message`, `intent`,
`service`, `arguments`, `execution_result`, `execution_status`,
`verification_result`, `verification_status`, `feedback`, `retry_count`, and
`final_response`. The notification graph has `task_id`, `request`,
`notifications`, and `final_response`. The runtime owns session, task, and event
records in `orchestration/store.py`. The read graph retains the legacy
`notifications` key for checkpoint compatibility and adds `observations` and
`source_status` for other read workflows, plus artifact path and bounded context
excerpt. Model budgets and health are stored with task and model records. A
separate `skill_executions` record pins the exact skill version used by each
read task; memory and skill records are owner-scoped.

### 5.2 Model configuration

`ORIN_MODEL` selects the primary model and defaults to
`openrouter:nvidia/nemotron-3.5-lightning:free`. `ORIN_FALLBACK_MODEL` optionally
selects a backup. The backend contract normalizes structured response, model
name, observed token usage, and known capabilities. `openrouter:` and `ollama:`
model identifiers use the installed LangChain integrations. Ollama uses native
JSON schema output. `ORIN_CONTEXT_TOKENS`, `ORIN_OUTPUT_RESERVE`,
`ORIN_TASK_MODEL_CALLS`, and `ORIN_TASK_MODEL_TOKENS` set conservative limits.
Missing provider quota is recorded as unknown. Rate limits apply a cooldown.

## 6. Running the foundation

Python 3.14 and uv are specified in `.python-version` and `pyproject.toml`.
Run `uv sync`. Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, and
`OPENROUTER_API_KEY` for Telegram with the default model. Set `GITHUB_TOKEN`
and `ORIN_GITHUB_ALLOWED_USERS` for the GitHub notifications capability. The
GitHub token must be a classic personal access token with `notifications` scope.
Set `ORIN_API_TOKEN` for the local API. See README for complete commands and
configuration. Use `uv run python -m pytest -q` for credential-free tests and
build the UI with `cd web && npm ci && npm run build`. Start the combined local
server with `uv run python -m orchestration.control_center` from the project root.
The terminal prints a one-time pairing code; restarting issues a new code.
Use
`uv run python -m evaluation.benchmark` for the scripted comparison. A small
local Ollama model can be set as `ORIN_FALLBACK_MODEL`. Run
`uv run python -m evaluation.learning` for the credential-free skill adoption
and rollback demonstration. Google read adapters use independent desktop OAuth
grants with refresh tokens in the OS credential store and matching
`ORIN_*_ALLOWED_USERS` grants. Short-lived environment access tokens remain
overrides. Run `uv run python -m evaluation.phase4_search` for the synthetic
cross-source search fixture and `uv run python -m orchestration.schedule_worker`
to dispatch due jobs. See `README.md` and `INTEGRATIONS.md` for setup and scopes.

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
| **1. Foundation** | FastAPI, durable LangGraph runtime, provider abstraction, capability registry, SQLite, sessions, streaming | Implemented; live GitHub and Telegram smoke checks passed on 2026-11-25 |
| **2. Context engineering** | Token budgeting, compression, retrieval, persistent task state, checkpoint recovery, fallback routing | Implemented; live cloud/local model and GitHub/Telegram checks passed |
| **3. Adaptive learning** | Owner-scoped memory, GitHub and cross-source briefing skills, evaluator, rollback | Implemented and credential-free end-to-end tested |
| **4. Autonomy** | Sync/search, scoped tools, MCP, bounded delegation, scheduler, approvals, narrow writes | Core implemented and credential-free tested; optional account and live write verification pending |
| **5. Interfaces** | Local Next.js static control center, Tauri shell, and deeper management views | 5B core implemented; Discord/Slack channel linking pending verification |
| **6. Hardening** | Benchmarks, recovery tests, security tests, migrations, backup/restore, installer | Not started |
| **7. Distributed** | Hub, Node, capability routing, selective sync | Not started |

### Recommended MVP slice (from the design discussion)

- **Runtime:** Python + FastAPI, LangGraph, SQLite, budget manager, free-provider
  routing, persistent memory, skill creation/retrieval.
- **Channels:** Telegram bot, local CLI, Tauri control panel.
- **Integrations:** GitHub, Gmail, Drive, Calendar, then Notion,
  filesystem, and terminal as permissions mature.
- **Agents:** main coordinator + research/coding/productivity, adaptive
  delegation, approvals, scheduled tasks.

Do not start with 15 integrations, six agents, and three frontends.

---

## 9. Current limits and decisions

- The GitHub workflow uses deterministic prioritization and a read-only GET
  operation. The required classic token has broader permissions than this code
  uses because GitHub's endpoint rejects fine-grained tokens.
- Gmail inbox headers, Drive metadata, and Calendar event reads passed live
  account checks on 2026-11-25. Optional source reads and narrow Google writes
  have only credential-free provider tests. Other GitHub/Gmail requests remain
  mock executions.
- Google uses desktop OAuth with PKCE, independent scopes and OS credential
  storage. The External Testing refresh tokens expire after seven days. The
  capability API reports local configuration, not current provider acceptance.
- The API supports a single configured owner for its bearer token and must be
  bound to localhost. Cancellation applies to pending and paused tasks.
- The learning loop currently applies to one read-only GitHub priority
  procedure. The local vector cache uses character n-grams and a linear scan;
  neural embeddings and approximate nearest-neighbor search remain future work.
- Provider quota discovery and distributed execution remain future work.
  Unknown quota remains explicit in model records.
- Phase 4 browser reads use a temporary profile and public-HTTPS precheck, but
  do not have a network sandbox. Trusted stdio MCP executables have host-user
  privileges. Calendar and optional source account labels are not verified by
  the provider. Existing Phase 0 mock actions do not pass through Phase 4 policy.
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

Verify packaged desktop start, stop, restart, and notification behavior on each
target OS. Then complete conditional Discord/Slack channel linking only with
verified account ownership and channel authorization. Phase 6 hardening follows.
Optional read adapters and Google write scopes still need live verification;
do not describe fixture-only integrations as live supported.

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
