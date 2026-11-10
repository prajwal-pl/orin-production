from telegram import Update
from telegram.ext import ContextTypes
from orchestration.nodes import GraphState
from orchestration.graph import graph


async def telegram_bot_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    message = update.message.text

    initial_state: GraphState = {
        "user_id": user_id,
        "message": message,
        "intent": "",
        "service": "other",
        "arguments": {},
        "execution_result": {},
        "execution_status": "pending",
        "feedback": "",
        "verification_result": {},
        "retry_count": 0,
        "final_response": "",
    }

    # Run classification to get an initial response
    result = await graph.ainvoke(initial_state)

    # Reply with a concise string derived from the classification result
    await update.message.reply_text(result.get("final_response", "Task completed"))
