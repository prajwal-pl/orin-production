# AGENTS.md

> **Read this file at the start of every session before changing code.**
> It is the shared context for humans and AI coding agents working on Orin.
> Last updated: 2026-11-09

---

## 1. Project identity

| Field | Value |
|---|---|
| Project name | **Orin** (called **ORION** in the original design discussion) |
| Repository | `orin` |
| Package name in `pyproject.toml` | `morrow` *(legacy/inconsistent — see §9)* |
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

## 3. Current state (what actually exists)

This repository is a **walking skeleton**, not the full runtime.

Implemented:

- Telegram long-polling bot (`python-telegram-bot`).
- A compiled LangGraph with four nodes: classify → (gmail | github | other) → verify.
- Two LLM agents built with `langchain.agents.create_agent`:
  - classifier (structured output into `Classification`)
  - verifier (structured output into `Verifier`)
- Pydantic schemas for classification and verification.
- Mock gmail/github task nodes that only `print()` and return a canned result.
- `.env` loading for `OPENROUTER_API_KEY` and `TELEGRAM_BOT_TOKEN`.

Not implemented yet:

- FastAPI gateway, HTTP/WebSocket API, streaming.
- SQLite persistence, sessions, tasks, checkpoints.
- Memory (episodic/semantic/procedural/preference/working).
- Skill registry/versioning/learning loop.
- Provider router, fallback, token/context budget manager.
- Real Gmail/GitHub/Notion/filesystem/terminal/browser/MCP integrations.
- Subagents/delegation, scheduler, approvals UI.
- Next.js/Tauri desktop control center.
- ORION Hub / ORION Node split.
- Tests, linting, CI, packaging.

**Do not describe unimplemented features as done** — not in code, docs, or
comments.

---

## 4. Repository map

```
orin/
├── main.py              # Entry point: builds Telegram Application, registers handlers
├── pyproject.toml       # uv project + dependencies (name is "morrow")
├── uv.lock              # Locked dependency graph (committed)
├── .python-version      # 3.14
├── .env                 # LOCAL SECRETS — gitignored, never commit or echo
├── .gitignore
├── README.md            # User-facing overview
├── AGENTS.md            # This file (agent/session context)
└── src/                 # namespace package (no __init__.py)
    ├── agents.py        # classifier + verifier (LangChain create_agent)
    ├── bot.py           # Telegram message handler; builds GraphState; invokes graph
    ├── graph.py         # LangGraph wiring (nodes + edges)
    ├── nodes.py         # State TypedDict + node functions + routing
    └── schema.py        # Classification and Verifier Pydantic models
```

### File responsibilities

| File | Owns | Notes |
|---|---|---|
| `main.py` | Telegram app lifecycle | `/start` handler + text handler |
| `src/bot.py` | Channel → runtime adapter | Builds initial state, awaits `graph.ainvoke`, replies |
| `src/graph.py` | Orchestration topology | Single source of truth for edges |
| `src/nodes.py` | State contract + node logic | Contains mock executors |
| `src/agents.py` | Model configuration + prompts | Both agents currently use the same free model |
| `src/schema.py` | Structured-output contracts | `Classification`, `Verifier` |

---

## 5. How the prototype works today

### 5.1 Request flow

```
Telegram user
    │  text message
    ▼
main.py  (MessageHandler)
    ▼
src/bot.py :: telegram_bot_message
    │  builds GraphState with defaults
    ▼
graph.ainvoke(state)
    ▼
START
  │
  ▼
classify  (classification_agent)
  │  LLM → Classification {type, intent, arguments}
  │  type → service: gmail-task→gmail, github-task→github, other→other
  ├── "github" ──▶ github (mock_github_task) ──▶ verify
  ├── "gmail"  ──▶ gmail  (mock_gmail_task)  ──▶ verify
  └── "other"  ─────────────────────────────▶ verify
                                                  │
                                                  ▼
                                                END
    ▼
bot.py replies with result["final_response"]
```

### 5.2 State contract (`GraphState` in `src/nodes.py`)

| Key | Type | Written by | Meaning |
|---|---|---|---|
| `user_id` | `str` | bot.py | Telegram user id (currently unused downstream) |
| `message` | `str` | bot.py | Raw user request |
| `intent` | `str` | classify | Extracted intent |
| `service` | `Literal["gmail","github","other"]` | classify | Routing key |
| `arguments` | `dict` | classify | Extracted task arguments |
| `execution_result` | `dict` | executors | Mock result payload |
| `execution_status` | `str` | executors | e.g. `completed` |
| `verification_result` | `dict` | verifier (intended) | Verification payload |
| `feedback` | `str` | verifier | Human-readable critique |
| `retry_count` | `int` | verifier | Retry counter (currently LLM-supplied) |
| `final_response` | `str` | verifier | Text sent back to the channel |

### 5.3 Nodes

| Node | Function | Behaviour |
|---|---|---|
| `classify` | `classification_agent` | Calls classifier, maps structured type to `service` |
| `github` | `mock_github_task` | Prints arguments, returns canned success |
| `gmail` | `mock_gmail_task` | Prints arguments, returns canned success |
| `verify` | `verification_agent` | Calls verifier with execution result + full state |

`other_task` and `verify_cycle` exist in `src/nodes.py` but are **not wired into
the graph**.

### 5.4 Model configuration

Both agents use:

```python
model="openrouter:nvidia/nemotron-3.5-lightning:free"
```

- Auth comes from `OPENROUTER_API_KEY`.
- `create_agent(..., response_format=ToolStrategy(Model))` forces structured output.
- No fallback model, retry policy, or token budget exists yet.
- Free model availability changes frequently; do not assume this model will
  remain available or remain free.

---

## 6. Running the prototype

### Prerequisites

- Python 3.14 (see `.python-version`)
- [`uv`](https://docs.astral.sh/uv/)
- An OpenRouter API key
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Setup

```bash
uv sync
```

Create `.env` in the repo root (already gitignored):

```dotenv
OPENROUTER_API_KEY=sk-or-...
TELEGRAM_BOT_TOKEN=123456:ABC...
```

### Run

```bash
uv run main.py
```

Then message the bot on Telegram. `/start` returns a greeting; any other text is
sent through the graph.

### Minimal smoke checks (no network)

```bash
# Syntax/compile every source file
uv run python - <<'PY'
import pathlib
for p in pathlib.Path(".").glob("**/*.py"):
    if ".venv" in str(p):
        continue
    compile(p.read_text(), str(p), "exec")
    print("OK", p)
PY
```

There is no test suite yet. If you add tests, prefer `pytest` and keep them
runnable without live provider/Telegram credentials by mocking the agents.

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
| **0. Prototype** | Telegram channel, LangGraph classify/verify, mock executors | **← we are here** |
| **1. Foundation** | FastAPI, durable LangGraph runtime, provider abstraction, tool registry, SQLite, sessions, streaming | Not started |
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

## 9. Known issues and landmines

These are real defects/inconsistencies in the current prototype. Fix them only
as part of an explicit task; do not silently "clean up" unrelated code.

1. **State key mismatch.** `verification_agent` writes
   `"verification_results"` (plural), but `GraphState` and the rest of the code
   use `verification_result` (singular). This will fail LangGraph state
   validation or silently lose the value.
2. **Retry loop is not wired.** `verify_cycle` is defined but never added to the
   graph; `verify` always goes to `END`. `retry_count` comes from the LLM rather
   than being incremented deterministically.
3. **`other_task` is dead code.** `other` routes directly to `verify`, so
   non-Gmail/GitHub requests are never executed.
4. **`verify_cycle` compares a dict to the string `"fail"`.**
   `verification_result` is typed as `dict` in `GraphState`, but the cycle check
   expects `"fail"`.
5. **Blocking calls in async handler.** `classifier.invoke` / `verifier.invoke`
   are synchronous inside the async Telegram handler; use `ainvoke` or a thread
   offload.
6. **No persistence.** Every message starts from a default state; `user_id` is
   collected but not used. No sessions, checkpoints, or conversation history.
7. **No error handling.** Provider failures, invalid JSON/structured output, and
   Telegram errors propagate without a user-facing message.
8. **No authentication/allowlist.** Anyone who discovers the bot can consume the
   owner's API quota.
9. **`final_response` may be `None`.** `Verifier.final_response` is
   `str | None`; replying with `None` can fail. Provide a deterministic fallback.
10. **Model is hardcoded.** No env override, capability check, quota tracking, or
    fallback. Free model IDs are volatile.
11. **Naming drift.** Folder is `orin`, bot says "Orin", design says "ORION",
    `pyproject.toml` says `morrow`, and the description is a placeholder.
    Reconcile deliberately, not accidentally.
12. **Python 3.14 target.** The design discussion assumes 3.12+; 3.14 is very new
    and may limit dependency compatibility. Confirm before lowering/raising.
13. **No tests/lint/CI.** Changes are currently verified only by running the bot.
14. **`.env` formatting.** Current file uses spaces around `=`; `dotenv` tolerates
    it, but prefer standard `KEY=value`. Never print or commit the file.
15. **`README.md` was historically empty.** Keep it and this file in sync with
    actual behavior.

---

## 10. Conventions

- **Package manager:** `uv` only. Add deps with `uv add`; commit `uv.lock`.
- **Python style:** small pure functions in `src/nodes.py`, model/prompt setup in
  `src/agents.py`, contracts in `src/schema.py`, wiring in `src/graph.py`.
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

### Highest-value next tasks (in order)

1. Fix the `verification_result` key mismatch.
2. Wire a deterministic retry loop (`verify_cycle` → re-execute or end) with a
   hard retry cap.
3. Route `other` to `other_task` (or delete it and document the behavior).
4. Add error handling + a guaranteed string fallback for Telegram replies.
5. Convert agent calls to async (`ainvoke`) or offload them.
6. Add a minimal test suite for state mapping, routing, and verifier output.
7. Add a Telegram user allowlist and validate required env vars at startup.
8. Make model/provider configurable and add one fallback model.
9. Introduce LangGraph checkpointing + SQLite session persistence.
10. Only then start Phase 1: FastAPI gateway, tool registry, provider router.

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
