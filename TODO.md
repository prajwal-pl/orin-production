# Orin development checklist

Orin has completed Phase 0. The Telegram prototype classifies requests, routes to mock Gmail and GitHub executors, and asks a model to produce a reply. Checked items describe implemented capabilities. The remaining items are implementation work.

The phase numbering follows the [README roadmap](README.md#roadmap) and [project architecture](AGENTS.md#7-target-architecture-north-star). Keep one Python runtime across channels and deployment profiles. The first portfolio milestone is a read-only GitHub workflow with durable execution and measurable model routing, delivered across Phases 1 and 2.

## Phase 0 — Stabilize the prototype

- [x] Wire a Telegram text handler to a LangGraph workflow.
- [x] Define structured classifier and verifier outputs and route Gmail and GitHub requests to mock executors.
- [x] Use `verification_result` consistently and define an explicit verification outcome that the graph can route on.
- [x] Let the runtime count retries. Wire a bounded retry path for retryable failures, with a terminal outcome when the cap is reached.
- [x] Give the `other` route an explicit response for unsupported requests.
- [x] Use async model calls and handle provider errors, malformed structured output, and empty replies with deterministic user-facing messages.
- [x] Validate required configuration at startup, authorize Telegram user IDs before invoking a model, and redact sensitive inputs from logs.
- [x] Centralize model configuration, support an environment override, and allow an optional fallback for transient provider failures.
- [x] Add credential-free tests for routing, verification, retry limits, authorization, and reply fallback.
- [x] Update README and AGENTS file paths to match `orchestration/`. Resolve package naming deliberately and document the supported Python and uv setup.

**Done when** the prototype passes its credential-free tests and every supported input path returns a meaningful reply, including simulated provider failures.

## Phase 1 — Build the runtime foundation

- [ ] Define reusable task, step, session, capability, and event contracts. Route Telegram and a minimal local CLI through the same runtime.
- [ ] Add versioned SQLite migrations for sessions, messages, tasks, steps, checkpoints, and execution records.
- [ ] Persist LangGraph checkpoints with stable task and session IDs. Define task transitions, cancellation, recovery, and duplicate-update handling.
- [ ] Define a capability registry with typed inputs and outputs, permission scopes, timeouts, and consistent error handling. Record tool outcomes in the execution history.
- [ ] Build the first real workflow. Fetch unread GitHub notifications with read-only credentials, group them by repository, and summarize items that need attention with source links.
- [ ] Store integration credentials through environment variables or the OS credential store. Keep secrets out of execution history and model context.
- [ ] Introduce a provider adapter contract that normalizes structured responses, capability information, usage, and errors. Migrate the prototype provider configuration into it and support a second backend.
- [ ] Add a localhost FastAPI gateway with authenticated session and task operations, status retrieval, and a streaming event endpoint that supports reconnecting.
- [ ] Test persistence and recovery by interrupting a run after its GitHub fetch has been checkpointed. Verify that resuming reuses the saved result and preserves task ownership.

**Done when** an authorized user can run the GitHub workflow through Telegram, inspect its saved status, and resume it after a process restart.

## Phase 2 — Engineer context and model budgets

- [ ] Define active, working, persistent, procedural, and archived context sources. Select material by task relevance and preserve the active objective and critical execution state.
- [ ] Count tokens with provider tokenizers where available, estimate conservatively elsewhere, and reserve capacity for model output.
- [ ] Persist raw tool outputs locally and pass bounded summaries or selected excerpts into model context. Expose only capabilities relevant to the current step.
- [ ] Record per-model capabilities, health, observed usage, quotas where available, and cooldowns. Handle unknown quota explicitly.
- [ ] Route work by task complexity and capability requirements. Apply per-task call and token limits, bounded retries, and checkpoint-aware fallback on transient failure.
- [ ] Define what the user sees when the runtime switches models, reduces work, or pauses because it has exhausted the budget.
- [ ] Exercise cloud and local inference through the same adapter contract. Add providers incrementally against the supported capability matrix.
- [ ] Build a versioned evaluation set for the GitHub workflow using sanitized fixtures. Include empty inboxes, duplicate notifications, malformed outputs, and rate limits.
- [ ] Compare single-model and budget-aware runs on identical inputs. Report task success, token use, latency, and fallback recovery. Record models, settings, and limitations.
- [ ] Document the portfolio milestone with a reproducible benchmark and a short demo showing real execution, restart recovery, and model fallback.

**Done when** a repeatable evaluation shows how routing affects quality and resource use, and injected provider failures produce a bounded fallback or a resumable pause.

## Phase 3 — Add memory and learning

- [ ] Define records and retention rules for episodic, semantic, procedural, preference, and working memory. Store provenance and isolate records by authorized user.
- [ ] Keep SQLite authoritative. Add FTS5 search, then a rebuildable local vector index and combined retrieval. Evaluate relevance on representative tasks.
- [ ] Support inspection, correction, export, and deletion of memory, including removal from indexes.
- [ ] Create a skill registry for built-in, custom, and learned skills. Version `SKILL.md` procedures and capture metadata, required permissions, and evaluation results.
- [ ] Generate skill proposals from successful runs. Validate proposals with fixtures, review changes when required, and retain rollback to a previous version.
- [ ] Track which skill version each run used. Prevent a learned skill from expanding permissions or modifying executable code or policy.
- [ ] Compare recurring tasks before and after adopting a skill. Track task success, model calls, and user corrections.

**Done when** a retrieved memory or versioned skill improves a recurring workflow in evaluation, and the user can inspect and reverse the change.

## Phase 4 — Add controlled autonomy

- [ ] Enforce policy at the capability boundary. Scope filesystem access to approved roots and account credentials to specific read or write operations.
- [ ] Persist approvals tied to the user, action parameters, and expiration. Enforce them for destructive actions and test denial, expiry, and replay.
- [ ] Introduce scoped filesystem tools, isolated terminal execution, and isolated browser sessions. Bound runtime, resource use, and output.
- [ ] Add MCP server registration and trust controls. Treat web pages, files, integration responses, and MCP outputs as untrusted data.
- [ ] Add Gmail and Notion workflows incrementally. Begin with read operations and test explicit approvals before enabling sensitive writes.
- [ ] Add durable scheduled jobs with time-zone handling, cancellation, missed-run behavior, and duplicate-run prevention.
- [ ] Add selective delegation within the shared runtime. Bound delegated tool permissions and inference budgets, and track child task progress and cancellation.
- [ ] Test approval bypass attempts, workspace escape attempts, untrusted tool content, and retries after an ambiguous external write.

**Done when** scheduled and delegated workflows obey permissions and budgets, and execution history records each action and approval.

## Phase 5 — Build the control center

- [ ] Build the Next.js control center on the existing gateway. Show live activity, task history, failures, and recovery controls.
- [ ] Add session, memory, skill version, model, and usage views. Expose approval, schedule, and node status controls as their runtime capabilities become available.
- [ ] Package the interface in Tauri and manage the local Python service lifecycle, including startup, shutdown, restart, and failure reporting.
- [ ] Support event reconnect and show stale or disconnected status. Verify that task controls remain usable with keyboard navigation.
- [ ] Keep channel adapters thin. Add Discord and Slack through the same runtime with account linking and channel-specific authorization.

**Done when** the desktop app can start the local runtime and an authorized user can inspect, approve, cancel, and recover work from the control center.

## Phase 6 — Harden and package releases

- [ ] Add CI for linting, type checks, unit and integration tests, and packaged smoke tests using locked dependencies and credential-free fixtures.
- [ ] Test interrupted migrations, concurrent submissions, duplicate messages, provider outages, and recovery after a crash.
- [ ] Maintain reproducible benchmarks for task success, latency, token consumption, and recovery. Document the test environment and flag regressions.
- [ ] Test secrets redaction, authorization boundaries, tool isolation, prompt injection handling, and audit event integrity.
- [ ] Implement user-controlled exports and backups for SQLite, skills, and artifacts. Test restoration to a clean profile and document schema compatibility.
- [ ] Provide optional local database encryption with a documented key and recovery strategy.
- [ ] Declare the release license, build the installer, and verify fresh installation, upgrades, and rollback on supported platforms.

**Done when** the release installs on a clean machine, survives the documented failure scenarios, and can restore a tested backup.

## Phase 7 — Deliver distributed Hub and Node execution

- [ ] Define Hub and Node deployment profiles for the shared runtime. Deploy the first self-hosted Hub for channel ingress, scheduling, coordination, and task persistence.
- [ ] Implement Node enrollment, identity, credential rotation, and revocation. Have Nodes initiate authenticated outbound HTTPS or WebSocket connections.
- [ ] Advertise per-device capabilities, scopes, and availability. Route operations only to eligible Nodes.
- [ ] Queue work when a required Node is offline. Use leases and acknowledgments to recover interrupted work and guard against duplicate side effects on reconnect.
- [ ] Define where checkpoints, memory, and artifacts live. Make synchronization selective, user-controlled, and encrypted in transit. Test conflict handling and revocation.
- [ ] Expose Node and queued-task status through the gateway and control center. Test multiple Nodes, reconnects, Hub restarts, and an unavailable required capability.

**Done when** a task submitted remotely waits while its required Node is offline, resumes when an authorized eligible Node reconnects, and produces an inspectable execution history.
