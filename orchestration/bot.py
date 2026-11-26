"""Telegram channel adapter for the prototype graph."""

import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from orchestration.graph import graph
from orchestration.nodes import GraphState
from orchestration.runtime import Runtime, capability_help, task_reply

logger = logging.getLogger(__name__)
PROVIDER_ERROR_REPLY = "I could not process that request right now. Please try again later."
DENIED_REPLY = "This Orin bot is private. Your account is not authorized."


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
    await safe_reply(update.message, capability_help(str(update.effective_user.id)))


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
