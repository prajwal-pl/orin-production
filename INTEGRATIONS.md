# Integration research and versatile workflow plan

Research date: 2026-11-25. This document separates working code from the
product opportunities it prepares for. Orin remains one runtime; a source
adapter contributes evidence to a shared task, memory, budget, artifact, and
skill path.

## Useful cross-service workflows

| Workflow | Sources | Value | Current status |
|---|---|---|---|
| Daily briefing | Calendar events, unread Gmail headers, recent Drive files, GitHub notifications | One view of today's commitments and changes, with source links and missing-source status | Shared read-only path and live Google OAuth reads verified |
| Meeting preparation | Calendar event metadata, matching Gmail headers, Drive/Notion titles | Find likely briefs and open questions before a meeting | Deterministic read workflow and fixture-tested cross-source search; full thread/content linking remains future work |
| Follow-up queue | Gmail headers, GitHub notifications, Calendar deadlines | Turn scattered obligations into a reviewable list | Deterministic metadata-only review queue; Todoist/Slack content is excluded from this procedure |
| Project pulse | GitHub activity, Drive documents, Notion pages, Slack decisions | Summarize changes with provenance and detect stale work | Planned; would need per-source sync and permissions |
| Availability planning | Calendar free/busy, task deadlines | Suggest open slots without reading event descriptions | Planned; Calendar has a narrower free/busy capability |
| Weekly review | Completed tasks, user corrections, calendar outcomes, project notes | Evaluate recurring workflows and propose bounded skill changes | Planned beyond the current briefing-order and GitHub-priority skills |

The first four read sources now share an evidence contract with source ID,
title, detail, link, and time. The runtime stores raw observations privately,
returns bounded context, records which capability ran, and can combine partial
results. A correction such as “calendar first” on a completed briefing proposes
a versioned ordering skill; the owner must activate it. This is a narrow,
inspectable example of cross-source learning.
Briefing items rotate across sources so a large inbox cannot hide every item
from another source; the skill controls the order of each round.

## Features that make the integrations useful

| Priority | Feature | Concrete behavior |
|---|---|---|
| Implemented core | Unified search with citations | Search owner-scoped source metadata and explicitly indexed local text; return source links, account labels, and fetch time. Content results require a separate grant. |
| Implemented core | Meeting preparation | Pick a likely event and related metadata by request terms; show cited items and possible questions. Rich entity/thread linking remains future work. |
| Implemented core | Follow-up review | Flag likely follow-ups from metadata for owner review; no external task or message is created. |
| Next | Connection and permission dashboard | Show which account, scope, owner grant, token expiry, and last successful sync apply to each capability. Make disconnected sources visible in task results. |
| Implemented core | Scheduled briefings | Run local one-time or daily tasks with timezone, missed-run behavior, and deduplication. Watchlists and notifications remain future work. |
| Implemented core | Approval queue and narrow actions | Prepare Gmail send, Calendar event, or Drive folder actions with exact parameters and an idempotency key; execute after owner approval. Live write scopes are not connected yet. |
| Later | Experience evaluation | Track whether retrieval, priorities, and skills improved recurring tasks using user corrections and task outcomes; allow rollback. |

This order keeps the project focused on cross-service outcomes rather than a
large list of shallow connectors. A source with a clear read contract can join
the evidence path before it gains write actions.

## Why these first adapters

| Source | Smallest useful read capability | Scope and important constraint |
|---|---|---|
| Gmail | Unread inbox message IDs, then Subject/From/Date headers | `gmail.metadata` excludes message bodies and **does not allow the `q` search parameter** on `messages.list`; use label filters for this view. It is a restricted scope, so public distribution has verification implications. [Scopes](https://developers.google.com/workspace/gmail/api/auth/scopes), [list method](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list), [get method](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get) |
| Drive | Recent file names, MIME types, modification times, and links | `drive.metadata.readonly` cannot download file content. `files.list` supports `q`, `fields`, ordering, and pagination. This scope is restricted. [Metadata](https://developers.google.com/workspace/drive/api/guides/file-metadata), [files.list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list), [scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) |
| Calendar | Upcoming event metadata | `calendar.events.readonly` supports events.list. For availability-only tasks, `calendar.freebusy` is narrower and freeBusy.query returns busy intervals without descriptions. [events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list), [freeBusy.query](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query) |
| GitHub | Unread notifications | Existing classic-token workflow, GET only, owner-gated. [Notifications API](https://docs.github.com/en/rest/activity/notifications) |

Google connections use separate desktop OAuth grants with PKCE and refresh
tokens in the OS credential store. Short-lived access tokens through
`ORIN_GMAIL_ACCESS_TOKEN`, `ORIN_DRIVE_ACCESS_TOKEN`, and
`ORIN_CALENDAR_ACCESS_TOKEN` remain explicit overrides. Each source requires the matching
`ORIN_GMAIL_ALLOWED_USERS`, `ORIN_DRIVE_ALLOWED_USERS`, or
`ORIN_CALENDAR_ALLOWED_USERS` owner grant. “Configured” in the API means a local
credential and owner grant are present; it does not certify that the provider
still accepts the token. The adapters use read-only GET operations and never
fetch Gmail bodies or Drive file contents. All three were live verified on
2026-11-25, along with a four-source briefing. Google External Testing refresh
tokens expire after seven days; reconnect each source to renew them.
Local disconnect removes one stored token. Google-side revocation invalidates
all grants to this project for the account, so Orin clears all local Google
credentials after a successful revoke.

## Phase 4 connector status and next verification

1. Paginated incremental Google metadata sync is implemented with durable
   owner/account cursors and credential-free provider tests. Gmail uses
   `historyId` and requires a full sync if history expires; Drive uses change
   page tokens; Calendar uses sync tokens and can require a full sync after 410.
   Live incremental sync on an actual changing account remains to be checked.
   [Gmail sync](https://developers.google.com/workspace/gmail/api/guides/sync),
   [Drive changes](https://developers.google.com/workspace/drive/api/guides/manage-changes),
   [Calendar sync](https://developers.google.com/workspace/calendar/api/guides/sync)
2. Owner-scoped search and metadata meeting preparation are implemented with
   citations and an approved local text path. Notion, Todoist, Slack, and
   Microsoft Graph have bounded read adapters with fixture tests but no live
   account verification yet. Their account IDs are configured labels, not
   provider-verified identities. Notion offers read-content capabilities,
   Slack scopes distinguish channel listing from message history, and Microsoft
   Graph has delegated permissions and delta queries.
   [Notion integration capabilities](https://www.notion.com/help/create-integrations-with-the-notion-api),
   [Slack history scopes](https://docs.slack.dev/messaging/retrieving-messages),
   [Microsoft Graph permissions](https://learn.microsoft.com/en-us/graph/permissions-overview),
   [Microsoft Graph delta](https://learn.microsoft.com/en-us/graph/delta-query-overview)
3. Todoist task reads are implemented and fixture tested. Todoist exposes `data:read` and
   separates it from write and delete permissions; granted scopes may be
   narrower than requested. [Todoist API](https://developer.todoist.com/api/v1/)
4. Narrow Google writes use capability grants, exact approvals, idempotency,
   and an audit trail. Ambiguous responses do not trigger another send/create;
   Calendar and Drive have read-only reconciliation, while Gmail requires
   manual Sent-mail review. Google write scopes and provider behavior still
   need live verification. MCP tool text is tagged lower trust. A trusted stdio
   MCP executable itself has host-user privileges, so only explicitly trusted
   local programs should be registered.
   [MCP skills security](https://skills.extensions.modelcontextprotocol.io/specification/beta/skills)

The portfolio demonstration can show the live four-source read briefing and a
cross-source synthetic run, then identify which future connectors still need
OAuth, live credentials, and provider testing. Keep automated adapter tests
distinct from the separate live account check.
