# Orin development checklist

Orin has completed Phases 0 through 3, implemented the Phase 4 controlled-autonomy core, and delivered the Phase 5A local web control center. Telegram, CLI, and a local API share a SQLite-backed runtime. GitHub notifications, Gmail headers, Drive metadata, and Calendar events have live-tested read-only adapters. Phase 4 adds incremental metadata sync, cited search, policy and approvals, bounded tools, schedules, delegation, and narrow Google writes with credential-free end-to-end tests. Optional provider adapters and Google write scopes have not been verified with live accounts. Other GitHub and Gmail requests still use mock actions. Checked items describe implemented behavior; unchecked items identify work that still needs evidence or implementation.

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

- [x] Define reusable task, step, session, capability, and event contracts. Route Telegram and a minimal local CLI through the same runtime.
- [x] Add versioned SQLite migrations for sessions, messages, tasks, steps, checkpoints, and execution records.
- [x] Persist LangGraph checkpoints with stable task and session IDs. Define task transitions, cancellation, recovery, and duplicate-update handling.
- [x] Define a capability registry with typed inputs and outputs, permission scopes, timeouts, and consistent error handling. Record tool outcomes in the execution history.
- [x] Build the first real workflow. Fetch unread GitHub notifications with GET requests and a classic token with the `notifications` scope, group by repository, and highlight items needing attention with source links. GitHub does not support fine-grained tokens for this endpoint.
- [x] Store integration credentials through environment variables or the OS credential store. Keep secrets out of execution history and model context.
- [x] Introduce a provider adapter contract that normalizes structured responses, capability information, usage, and errors. Migrate the prototype provider configuration into it and support a second backend.
- [x] Add a localhost FastAPI gateway with authenticated session and task operations, status retrieval, and a streaming event endpoint that supports reconnecting.
- [x] Test persistence and recovery by interrupting a run after its GitHub fetch has been checkpointed. Verify that resuming reuses the saved result and preserves task ownership.

**Done when** an authorized user can run the GitHub workflow through Telegram, inspect its saved status, and resume it after a process restart.

## Phase 2 — Engineer context and model budgets

- [x] Define active, working, persistent, procedural, and archived context sources. Select material by task relevance and preserve the active objective and critical execution state.
- [x] Count tokens with provider tokenizers where available, estimate conservatively elsewhere, and reserve capacity for model output.
- [x] Persist raw tool outputs locally and pass bounded summaries or selected excerpts into model context. Expose only capabilities relevant to the current step.
- [x] Record per-model capabilities, health, observed usage, quotas where available, and cooldowns. Handle unknown quota explicitly.
- [x] Route work by task complexity and capability requirements. Apply per-task call and token limits, bounded retries, and checkpoint-aware fallback on transient failure.
- [x] Define what the user sees when the runtime switches models, reduces work, or pauses because it has exhausted the budget.
- [x] Exercise cloud and local inference through the same adapter contract. Add providers incrementally against the supported capability matrix.
- [x] Build a versioned evaluation set for the GitHub workflow using sanitized fixtures. Include empty inboxes, duplicate notifications, malformed outputs, and rate limits.
- [x] Compare single-model and budget-aware runs on identical inputs. Report task success, token use, latency, and fallback recovery. Record models, settings, and limitations.
- [x] Document the portfolio milestone with a reproducible benchmark and a short demo showing real execution, restart recovery, and model fallback.

**Done when** a repeatable evaluation shows how routing affects quality and resource use, and injected provider failures produce a bounded fallback or a resumable pause.

## Phase 3 — Add memory and learning

- [x] Define records and retention rules for episodic, semantic, procedural, preference, and working memory. Store provenance and isolate records by authorized user.
- [x] Keep SQLite authoritative. Add FTS5 search and a rebuildable local character-gram vector cache for combined retrieval. Evaluate relevance on representative synthetic queries. Neural semantic embeddings remain future work.
- [x] Support inspection, correction, export, and deletion of memory, including removal from indexes.
- [x] Create a skill registry for built-in, custom, and learned GitHub priority skills. Version `SKILL.md` procedures and capture metadata, required permissions, and evaluation results.
- [x] Generate priority skill proposals from successful GitHub runs. Validate proposals with fixtures, require explicit owner activation, and retain rollback to a previous version.
- [x] Track which skill version each read workflow used. Prevent a learned skill from expanding permissions or modifying executable code or policy.
- [x] Compare recurring GitHub and briefing tasks before and after adopting a skill. Track task success, model calls, and user corrections.
- [x] Use one read-only evidence contract for GitHub, Gmail headers, Drive metadata, and Calendar events. Combine configured sources in a briefing, preserve partial-failure status, and record artifacts and episodes through the shared runtime.
- [x] Let a correction to a completed briefing propose a validated source-order skill; require explicit activation and support rollback.

**Done when** a retrieved memory or versioned skill improves a recurring workflow in evaluation, and the user can inspect and reverse the change.

## Phase 4 — Add controlled autonomy

- [x] Implement Google desktop OAuth with PKCE, independent least-privilege grants for Gmail, Drive, and Calendar, refresh-token storage in the OS credential store, revocation, and live account checks.
- [x] Add paginated and incremental read sync: Gmail history IDs, Drive change tokens, Calendar sync tokens, and full-resync recovery on expired cursors. Keep each source's data and provenance owner-scoped. Provider-shaped tests cover cursor behavior; live incremental changes remain unverified.
- [x] Build owner-scoped cross-source search with citations, account labels, freshness, and metadata/content separation. Evaluate retrieval across at least two providers and local files. Google Gmail/Drive identities are provider-checked during sync; Calendar and optional source labels remain unverified.
- [x] Enforce policy at the new Phase 4 capability boundary. Scope filesystem access to approved roots and account credentials to specific read or write operations. Existing Phase 0 mock actions are outside this new boundary and remain prototype-only.
- [x] Persist approvals tied to the user, action parameters, and expiration. Enforce them for destructive actions and test denial, expiry, and replay.
- [x] Introduce scoped filesystem tools, Docker-isolated terminal execution, and temporary-profile browser sessions. Bound runtime, resource use, and output. Browser sessions are profile-isolated, not network-sandboxed.
- [x] Add stdio MCP server registration and trust controls. Treat web pages, files, integration responses, and MCP outputs as untrusted data. Trusted MCP executables still have host-user privileges.
- [x] Extend metadata-only read workflows for meeting preparation and follow-up queues; add fixture-tested Notion, Todoist, Slack, and Microsoft Graph read adapters according to `INTEGRATIONS.md`.
- [ ] Verify Notion, Todoist, Slack, and Microsoft Graph scopes and behavior with live owner accounts before describing them as live-supported integrations.
- [x] Add narrow Gmail send, Calendar event create, and Drive folder create actions after exact approval and idempotency. Ambiguous outcomes stop retries; Calendar/Drive can be reconciled by reads, Gmail requires manual review. Provider-shaped tests pass; write scopes are not live-connected.
- [ ] Verify Google write scopes and one explicitly approved live action for each write capability, when the owner chooses to connect those scopes.
- [x] Add durable scheduled jobs with time-zone handling, cancellation, missed-run behavior, and duplicate-run prevention.
- [x] Add selective delegation within the shared runtime. Bound delegated read capabilities and inference budgets, and track child task progress and cancellation.
- [x] Test approval bypass attempts, workspace escape attempts, untrusted tool content, and retries after an ambiguous external write.

**Core done when** scheduled and delegated workflows obey permissions and budgets, and execution history records each action and approval. This is covered by credential-free tests and a fictional Aurora launch API scenario. Live optional-account and Google-write verification remain open above.

## Phase 5 — Build the control center

### 5A — Local web release

- [x] Create a TypeScript Next.js static-export app in `web/`, with UI components, typed API access, and static assets separated cleanly. Keep FastAPI as the only runtime server.
- [x] Serve the built UI and existing API from one loopback origin. Start both with one local command; fail clearly when the UI has not been built.
- [x] Add one-time browser pairing, an HttpOnly local session, session expiry/logout, same-origin and CSRF checks for cookie-authenticated writes. Preserve bearer-token API clients and owner isolation; never embed an API token in browser assets.
- [x] Show task counts, recent activity, failures, task detail, usage, model health, and source configuration. Label local configuration separately from provider-verified connectivity.
- [x] Allow task submission, run/resume, and cancellation through the shared runtime. Show event updates with reconnect and a disconnected state.
- [x] Add review screens for exact action approvals and scheduled jobs, including their status and cancellation controls. Keep dangerous operations behind existing approvals.
- [x] Make the UI responsive and keyboard usable. Test pairing, authorization, refresh, tasks, approvals, and schedules end to end in a real browser against a local server.
- [x] Refine the local UI as a task-first workbench with a documented color, type, spacing, state, and motion system. Verify core text contrast and reduced-motion behavior, and check desktop and narrow browser layouts against real task data.
- [x] Add system-aware light/dark mode, a persistent browser preference, and an Orin favicon. Check both themes and the favicon through the local service.

**5A done when** an authorized owner can start one local service, pair a browser at `127.0.0.1`, inspect live state, submit and recover a task, and review approvals without a Node server or cloud-hosted UI.

### 5B — Packaged desktop release

- [ ] Package the same static UI with Tauri and bundle/manage the Python runtime as a sidecar. Show startup, shutdown, restart, and failure status; retain the browser URL as an alternative interface.
- [ ] Add deeper session, memory, skill version, model, usage, and connection management views. Show token expiry and last successful provider check only when verified data exists.
- [ ] Add OS notifications and optional tray behavior without creating a second agent runtime.
- [ ] Keep channel adapters thin. Add Discord and Slack through the shared runtime with account linking and channel-specific authorization when those connections are verified.

**Phase 5 done when** the packaged app starts the local runtime and the same authorized controls work in both desktop and browser views.

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
