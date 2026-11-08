from dotenv import load_dotenv
from typing_extensions import TypedDict, Literal
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ContextTypes,
    Application,
    filters,
)
from telegram import Update
from agents import classifier, verifier
from langgraph.graph import StateGraph, START, END
import os

load_dotenv()

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")


class GraphState(TypedDict):
    user_id: str
    message: str

    intent: str
    service: Literal["gmail", "github", "other"]
    arguments: dict

    # Execution
    execution_result: dict
    execution_status: str

    # Verification
    verification_result: dict
    feedback: str
    retry_count: int

    # Final response
    final_response: str


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


def classification_agent(state: GraphState):
    result = classifier.invoke(
        {"messages": [{"role": "user", "content": state["message"]}]},
    )

    classification = result["structured_response"]

    service_mapping = {"gmail-task": "gmail", "github-task": "github", "other": "other"}

    return {
        "intent": classification.intent,
        "service": service_mapping[classification.type],
        "arguments": classification.arguments,
    }


def verification_agent(state: GraphState):
    result = verifier.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": f"execution_result: {state["execution_result"]}, execution_status: {state["execution_status"]}, state: {state}",
                }
            ]
        }
    )

    verification = result["structured_response"]

    return {
        "feedback": verification.feedback,
        "retry_count": verification.retry_count,
        "verification_results": verification.verification_result,
        "final_response": verification.final_response,
    }


def mock_github_task(state: GraphState):
    print(f"Mock github task running: {state['arguments']}")

    return {
        "execution_status": "completed",
        "execution_result": {"message": "github task executed"},
    }


def mock_gmail_task(state: GraphState):
    print(f"Mock gmail task running: {state['arguments']}")

    return {
        "execution_status": "completed",
        "execution_result": {"message": "gmail task executed"},
    }


def other_task(state: GraphState):
    print(f"Other task running: {state['arguments']}")

    return {
        "execution_status": "completed",
        "execution_result": {"message": "Other task executed"},
    }


def route_task(state: GraphState):
    return state["service"]


def verify_cycle(state: GraphState) -> GraphState:
    # If verification failed and we've exceeded max retries, mark as failed
    if state.get("verification_result") == "fail" and state.get("retry_count", 0) >= 3:
        return {
            **state,
            "execution_status": "failed",
            "feedback": "Max retries exceeded",
        }
    # Otherwise keep the state unchanged
    return state


builder = StateGraph(GraphState)

builder.add_node("classify", classification_agent)
builder.add_node("github", mock_github_task)
builder.add_node("gmail", mock_gmail_task)
builder.add_node("verify", verification_agent)

builder.add_edge(START, "classify")
builder.add_conditional_edges(
    "classify", route_task, {"github": "github", "gmail": "gmail", "other": "verify"}
)
builder.add_edge("github", "verify")
builder.add_edge("gmail", "verify")
builder.add_edge("verify", END)

graph = builder.compile()


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
