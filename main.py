from dotenv import load_dotenv
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ContextTypes,
    Application,
    filters,
)
from telegram import Update
from src.bot import telegram_bot_message
import os

load_dotenv()

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I'm Orin. What can I do for you?")


def main():
    application = Application.builder().token(bot_token).build()

    application.add_handler(CommandHandler("start", start))

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_bot_message)
    )

    application.run_polling()


if __name__ == "__main__":
    main()
