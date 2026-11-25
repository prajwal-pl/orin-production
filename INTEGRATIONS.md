# Integration research and versatile workflow plan

Research date: 2026-11-25. This document separates working code from the
product opportunities it prepares for. Orin remains one runtime; a source
adapter contributes evidence to a shared task, memory, budget, artifact, and
skill path.

## Useful cross-service workflows

| Workflow | Sources | Value | Current status |
|---|---|---|---|
| Daily briefing | Calendar events, unread Gmail headers, recent Drive files, GitHub notifications | One view of today's commitments and changes, with source links and missing-source status | Shared read-only path implemented; Google adapters require user-supplied access tokens |
| Meeting preparation | Calendar attendee/context, recent mail thread, matching Drive/Notion docs | Find the brief and open questions before a meeting | Planned; requires scoped search and entity linking |
| Follow-up queue | Mail requiring reply, assigned GitHub reviews, Todoist tasks, calendar deadlines | Turn scattered obligations into a reviewable list | Planned; no external writes yet |
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
| Next | Unified search with citations | Search permitted mail headers, file metadata, event titles, notes, and local files; return source links, account identity, and freshness for each hit. Keep content retrieval separate from metadata search. |
| Next | Meeting preparation | Resolve an event to likely documents, recent messages, people, and open questions; show why each item was selected. Start read-only. |
| Next | Follow-up review | Detect requests and deadlines across mail, GitHub, task manager, and calendar; ask the owner to confirm before creating tasks or messages. |
| Next | Connection and permission dashboard | Show which account, scope, owner grant, token expiry, and last successful sync apply to each capability. Make disconnected sources visible in task results. |
| Later | Scheduled briefings and watchlists | Run bounded recurring tasks with timezone, missed-run behavior, deduplication, and notification preferences. |
| Later | Approval queue and draft actions | Prepare a proposed email, event, or task with a diff and idempotency key; execute only after explicit approval. |
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

The current Google code accepts **separate, short-lived access tokens** through
`ORIN_GMAIL_ACCESS_TOKEN`, `ORIN_DRIVE_ACCESS_TOKEN`, and
`ORIN_CALENDAR_ACCESS_TOKEN`, and requires the matching
`ORIN_GMAIL_ALLOWED_USERS`, `ORIN_DRIVE_ALLOWED_USERS`, or
`ORIN_CALENDAR_ALLOWED_USERS` owner grant. It has
no consent flow or refresh-token storage yet. “Configured” in the API means an
environment token and owner grant are present; it does not certify that the
provider accepted the token or scope. The tested adapters use read-only GET
operations and never fetch Gmail bodies or Drive file contents.

## Next connector work

1. Add Google desktop OAuth with PKCE, per-capability consent, refresh, and OS
   credential storage. Google documents PKCE and secure refresh-token handling
   for installed apps. [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)
2. Add paginated and incremental read sync with durable cursors. Gmail uses
   `historyId` and requires a full sync if history expires; Drive uses change
   page tokens; Calendar uses sync tokens and can require a full sync after 410.
   [Gmail sync](https://developers.google.com/workspace/gmail/api/guides/sync),
   [Drive changes](https://developers.google.com/workspace/drive/api/guides/manage-changes),
   [Calendar sync](https://developers.google.com/workspace/calendar/api/guides/sync)
3. Add search and link resolution for meeting preparation. Keep provenance and
   access control on each retrieved item. Notion offers read-content
   capabilities, Slack scopes distinguish channel listing from message history,
   and Microsoft Graph has delegated permissions and delta queries.
   [Notion integration capabilities](https://www.notion.com/help/create-integrations-with-the-notion-api),
   [Slack history scopes](https://docs.slack.dev/messaging/retrieving-messages),
   [Microsoft Graph permissions](https://learn.microsoft.com/en-us/graph/permissions-overview),
   [Microsoft Graph delta](https://learn.microsoft.com/en-us/graph/delta-query-overview)
4. Add task-manager reads before task writes. Todoist exposes `data:read` and
   separates it from write and delete permissions; granted scopes may be
   narrower than requested. [Todoist API](https://developer.todoist.com/api/v1/)
5. Gate writes at the capability boundary with approval, idempotency, and an
   audit trail. MCP tools and remote skills must be treated as lower-trust
   inputs; connected servers do not grant implicit local execution.
   [MCP skills security](https://skills.extensions.modelcontextprotocol.io/specification/beta/skills)

The portfolio demonstration should show one real read capability and one
cross-source synthetic run, then clearly identify which other connectors still
need OAuth, live credentials, and provider testing. Avoid presenting adapter
tests as proof of live account connectivity.
