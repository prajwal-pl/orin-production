import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from orchestration.agents import configured_models
from orchestration.bot import DENIED_REPLY, allowed_user_ids, is_authorized, safe_reply, telegram_bot_message

load_dotenv()


def validate_configuration() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    allowed_user_ids()
    if any(value.startswith("openrouter:") for value in configured_models()):
        if not os.getenv("OPENROUTER_API_KEY", "").strip():
            raise ValueError("OPENROUTER_API_KEY is required for an OpenRouter model")
    return token


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not is_authorized(update):
        await safe_reply(update.message, DENIED_REPLY)
        return
    await safe_reply(update.message, "Hello! I'm Orin. What can I do for you?")


def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_bot_message))
    return application


def main():
    build_application(validate_configuration()).run_polling()


if __name__ == "__main__":
    main()
