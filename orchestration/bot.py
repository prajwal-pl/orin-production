"""Telegram channel adapter for the prototype graph."""

import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from orchestration.graph import graph
from orchestration.nodes import GraphState

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

    initial_state: GraphState = {
        "user_id": str(update.effective_user.id),
        "message": update.message.text,
        "intent": "",
        "service": "other",
        "arguments": {},
        "execution_result": {},
        "execution_status": "pending",
        "feedback": "",
        "verification_result": {},
        "verification_status": "pending",
        "retry_count": 0,
        "final_response": "",
    }
    try:
        result = await graph.ainvoke(initial_state)
        reply = result.get("final_response") or PROVIDER_ERROR_REPLY
    except Exception:
        logger.error("Telegram request failed")
        reply = PROVIDER_ERROR_REPLY
    await safe_reply(update.message, reply)
