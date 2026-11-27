"""Telegram channel adapter for the shared runtime."""

import json
import logging
import os
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from orchestration.graph import graph
from orchestration.nodes import GraphState
from orchestration.policy import PolicyDenied
from orchestration.runtime import Runtime, capability_help, task_reply

logger = logging.getLogger(__name__)
PROVIDER_ERROR_REPLY = "I could not process that request right now. Please try again later."
DENIED_REPLY = "This Orin bot is private. Your account is not authorized."
MAX_MESSAGE = 3800


def _args(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    return list(getattr(context, "args", None) or [])


def _short(value: object, limit: int = 500) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return text[:limit] + ("…" if len(text) > limit else "")


def _parameters(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text[:700] + ("…" if len(text) > 700 else "")


def _utc(value: object) -> str:
    try:
        stamp = float(value)
        return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return "unknown"


def _utc_text(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return "unknown"


def allowed_user_ids() -> set[int]:
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    try:
        ids = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError as error:
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain comma-separated numeric user IDs") from error
    if not ids:
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain at least one user ID")
    return ids


def is_authorized(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id in allowed_user_ids()


async def safe_reply(message, reply: str):
    try:
        await message.reply_text(reply)
    except Exception:
        logger.error("Telegram reply failed")


async def telegram_bot_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    if not update.message.text:
        return

    try:
        owner = str(update.effective_user.id)
        service = Runtime()
        session_id = f"telegram:{owner}"
        message_id = getattr(update.message, "message_id", None)
        key = f"telegram:{owner}:{message_id}" if message_id is not None else None
        task = await service.submit(owner, session_id, update.message.text, key)
        result = await service.run(owner, task["id"])
        reply = task_reply(result)
    except PermissionError:
        logger.warning("Telegram request denied")
        reply = "This capability is not enabled for your account."
    except KeyError:
        reply = "Task not found."
    except Exception:
        logger.error("Telegram request failed")
        reply = PROVIDER_ERROR_REPLY
    await safe_reply(update.message, reply)


async def telegram_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    owner = str(update.effective_user.id)
    commands = (
        "\n\nCommands:\n"
        "/status TASK_ID\n"
        "/resume TASK_ID\n"
        "/cancel TASK_ID\n"
        "/approvals\n"
        "/approve APPROVAL_ID [confirm]\n"
        "/deny APPROVAL_ID\n"
        "/schedules\n"
        "/unschedule JOB_ID\n"
        "/mcp\n"
        "/mcpconfirm CALL_ID\n"
        "/mcpdeny CALL_ID\n"
        "/actions\n"
        "/runaction ACTION_ID [confirm]\n"
        "/reconcile ACTION_ID"
    )
    await safe_reply(update.message, capability_help(owner, Runtime().policy) + commands)


async def telegram_task_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    if not context.args:
        await safe_reply(update.message, "Use /status TASK_ID")
        return
    task = Runtime().store.get_task(context.args[0], str(update.effective_user.id))
    if task is None:
        await safe_reply(update.message, "Task not found.")
        return
    await safe_reply(update.message, task_reply(task))


async def telegram_resume_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    if not context.args:
        await safe_reply(update.message, "Use /resume TASK_ID")
        return
    try:
        task = await Runtime().run(str(update.effective_user.id), context.args[0])
    except KeyError:
        await safe_reply(update.message, "Task not found.")
        return
    except PermissionError:
        await safe_reply(update.message, "This capability is not enabled for your account.")
        return
    await safe_reply(update.message, task_reply(task))


def _approval_text(approval: dict, linked: dict | None = None) -> str:
    lines = [
        f"Approval {approval['id']}",
        f"Capability: {approval['capability']}",
        f"Status: {approval['status']}",
        f"Expires: {_utc(approval['expires_at'])}",
        "Parameters:",
        _parameters(approval["parameters"]),
    ]
    if linked:
        lines.append(f"Linked action: {linked['id']} ({linked['status']})")
    return "\n".join(lines)


async def telegram_approvals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    owner = str(update.effective_user.id)
    service = Runtime()
    approvals = [item for item in service.policy.list_approvals(owner)
                 if item["status"] in {"pending", "approved"}]
    if not approvals:
        await safe_reply(update.message, "No pending approvals.")
        return
    linked = {item["approval_id"]: item for item in service.actions.list(owner)}
    lines = [f"Approvals awaiting review: {len(approvals)}"]
    for approval in approvals[:8]:
        lines.extend(["", _approval_text(approval, linked.get(approval["id"]))])
    if len(approvals) > 8:
        lines.append(f"\n… and {len(approvals) - 8} more")
    lines.append("\nReview first: /approve ID\nThen approve: /approve ID confirm\nDeny: /deny ID")
    await safe_reply(update.message, "\n".join(lines)[:MAX_MESSAGE])


async def telegram_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    args = _args(context)
    if not args:
        await safe_reply(update.message, "Use /approve APPROVAL_ID, then /approve APPROVAL_ID confirm")
        return
    owner = str(update.effective_user.id)
    approval_id = args[0].strip()
    service = Runtime()
    approval = service.policy.get_approval(owner, approval_id)
    if approval is None:
        await safe_reply(update.message, "Approval not found.")
        return
    if approval["status"] != "pending":
        await safe_reply(update.message, f"This approval is already {approval['status']}.")
        return
    linked = next((item for item in service.actions.list(owner)
                   if item["approval_id"] == approval_id), None)
    if len(args) == 1:
        reply = (_approval_text(approval, linked) +
                 f"\n\nSend /approve {approval_id} confirm to approve exactly this action.")
        await safe_reply(update.message, reply[:MAX_MESSAGE])
        return
    if len(args) != 2 or args[1].lower() != "confirm":
        await safe_reply(update.message, "Use /approve APPROVAL_ID confirm")
        return
    try:
        service.policy.approve(owner, approval_id)
    except PolicyDenied:
        await safe_reply(update.message, "Approval is expired or no longer available.")
        return
    reply = f"Approved {approval_id}. The approval is single-use."
    if linked:
        reply += (f"\nLinked action {linked['id']} is {linked['status']}. "
                  "Run it from the control center or local API.")
    await safe_reply(update.message, reply)


async def telegram_deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    args = _args(context)
    if not args:
        await safe_reply(update.message, "Use /deny APPROVAL_ID")
        return
    owner = str(update.effective_user.id)
    try:
        service = Runtime()
        service.policy.deny(owner, args[0].strip())
    except PolicyDenied:
        await safe_reply(update.message, "Approval is unavailable or already used.")
        return
    await safe_reply(update.message, f"Denied {args[0].strip()}.")


async def telegram_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    args = _args(context)
    if not args:
        await safe_reply(update.message, "Use /cancel TASK_ID")
        return
    owner = str(update.effective_user.id)
    service = Runtime()
    task = service.store.get_task(args[0].strip(), owner)
    if task is None:
        await safe_reply(update.message, "Task not found.")
        return
    if task["status"] not in {"pending", "paused"}:
        await safe_reply(update.message,
                         f"Only pending or paused tasks can be cancelled. This task is {task['status']}.")
        return
    cancelled = service.cancel(owner, task["id"])
    await safe_reply(update.message, f"Task {task['id']} is {cancelled['status']}.")


async def telegram_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    owner = str(update.effective_user.id)
    service = Runtime()
    jobs = [job for job in service.schedules.list(owner) if job["status"] == "active"]
    if not jobs:
        await safe_reply(update.message,
                         "No active schedules. Create one from the control center or local API.")
        return
    lines = [f"Active schedules: {len(jobs)}"]
    for job in jobs[:8]:
        lines.extend([
            "",
            f"Job {job['id']}",
            f"{job['recurrence']} · {job['timezone']}",
            f"Next: {_utc_text(job['next_run_at'])}",
            f"Request: {_short(job['request'], 180)}",
        ])
    if len(jobs) > 8:
        lines.append(f"\n… and {len(jobs) - 8} more")
    lines.append("\nCancel one: /unschedule JOB_ID")
    await safe_reply(update.message, "\n".join(lines)[:MAX_MESSAGE])


async def telegram_unschedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    args = _args(context)
    if not args:
        await safe_reply(update.message, "Use /unschedule JOB_ID")
        return
    owner = str(update.effective_user.id)
    service = Runtime()
    cancelled = service.schedules.cancel(owner, args[0].strip())
    if not cancelled:
        await safe_reply(update.message, "Schedule not found or already finished.")
        return
    await safe_reply(update.message, f"Schedule {args[0].strip()} cancelled.")


def _mcp_text(call: dict) -> str:
    return "\n".join([
        f"MCP call {call['id']}",
        f"Server: {call['server_id']}",
        f"Tool: {call['tool']}",
        f"Arguments: {_parameters(call['arguments'])}",
        f"Expires: {_utc(call['expires_at'])}",
    ])


async def telegram_mcp_calls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    owner = str(update.effective_user.id)
    calls = Runtime().mcp_calls.list_pending(owner)
    if not calls:
        await safe_reply(update.message, "No MCP calls are awaiting confirmation.")
        return
    lines = [f"MCP calls awaiting confirmation: {len(calls)}"]
    for call in calls[:8]:
        lines.extend(["", _mcp_text(call)])
    if len(calls) > 8:
        lines.append(f"\n… and {len(calls) - 8} more")
    lines.append("\nConfirm: /mcpconfirm CALL_ID\nDeny: /mcpdeny CALL_ID")
    await safe_reply(update.message, "\n".join(lines)[:MAX_MESSAGE])


async def telegram_mcp_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    args = _args(context)
    if not args:
        await safe_reply(update.message, "Use /mcpconfirm CALL_ID")
        return
    owner = str(update.effective_user.id)
    try:
        result = await Runtime().confirm_mcp_call(owner, args[0].strip())
    except KeyError:
        await safe_reply(update.message, "MCP call not found, expired, or already claimed.")
        return
    except Exception as error:
        await safe_reply(update.message, f"MCP call failed ({type(error).__name__}).")
        return
    text = f"Untrusted MCP observation ({result['server_id']}/{result['tool']}):\n{result['text']}"
    await safe_reply(update.message, text[:MAX_MESSAGE])


async def telegram_mcp_deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    args = _args(context)
    if not args:
        await safe_reply(update.message, "Use /mcpdeny CALL_ID")
        return
    try:
        Runtime().deny_mcp_call(str(update.effective_user.id), args[0].strip())
    except KeyError:
        await safe_reply(update.message, "MCP call not found or already decided.")
        return
    await safe_reply(update.message, f"MCP call {args[0].strip()} denied.")


def _action_text(action: dict, approval: dict | None = None) -> str:
    lines = [
        f"Action {action['id']}",
        f"Capability: {action['capability']}",
        f"Status: {action['status']}",
        f"Parameters: {_parameters(action['parameters'])}",
    ]
    if approval:
        lines.append(f"Approval: {approval['status']} (expires {_utc(approval['expires_at'])})")
    return "\n".join(lines)


async def telegram_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    owner = str(update.effective_user.id)
    service = Runtime()
    actions = service.actions.list(owner)
    if not actions:
        await safe_reply(update.message, "No prepared or executed actions.")
        return
    lines = [f"Actions: {len(actions)}"]
    for action in actions[:8]:
        approval = service.policy.get_approval(owner, action["approval_id"])
        lines.extend(["", _action_text(action, approval)])
    if len(actions) > 8:
        lines.append(f"\n… and {len(actions) - 8} more")
    lines.append("\nReview/run: /runaction ACTION_ID\nReconcile: /reconcile ACTION_ID")
    await safe_reply(update.message, "\n".join(lines)[:MAX_MESSAGE])


async def telegram_run_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    args = _args(context)
    if not args:
        await safe_reply(update.message, "Use /runaction ACTION_ID, then /runaction ACTION_ID confirm")
        return
    owner = str(update.effective_user.id)
    service = Runtime()
    action = service.actions.get(owner, args[0].strip())
    if action is None:
        await safe_reply(update.message, "Action not found.")
        return
    if action["status"] != "prepared":
        await safe_reply(update.message, f"This action is already {action['status']}.")
        return
    approval = service.policy.get_approval(owner, action["approval_id"])
    if len(args) == 1:
        reply = (_action_text(action, approval) +
                 f"\n\nSend /runaction {action['id']} confirm to execute exactly this action.")
        await safe_reply(update.message, reply[:MAX_MESSAGE])
        return
    if len(args) != 2 or args[1].lower() != "confirm":
        await safe_reply(update.message, "Use /runaction ACTION_ID confirm")
        return
    try:
        result = await service.actions.execute(owner, action["id"])
    except Exception as error:
        await safe_reply(update.message, f"Action could not run ({type(error).__name__}).")
        return
    await safe_reply(update.message, f"Action {action['id']} is {result['status']}.")


async def telegram_reconcile_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    args = _args(context)
    if not args:
        await safe_reply(update.message, "Use /reconcile ACTION_ID")
        return
    owner = str(update.effective_user.id)
    service = Runtime()
    action = service.actions.get(owner, args[0].strip())
    if action is None:
        await safe_reply(update.message, "Action not found.")
        return
    if action["status"] not in {"unknown", "executing"}:
        await safe_reply(update.message, f"No reconciliation is needed; this action is {action['status']}.")
        return
    try:
        result = await service.actions.reconcile(owner, action["id"])
    except Exception as error:
        await safe_reply(update.message, f"Reconciliation failed ({type(error).__name__}).")
        return
    await safe_reply(update.message, f"Action {action['id']} is {result['status']}.")
