"""Graph state and prototype task nodes."""

import json
import logging
from typing import Literal
from typing_extensions import TypedDict

from orchestration.agents import invoke_structured

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


class GraphState(TypedDict):
    user_id: str
    message: str
    intent: str
    service: Literal["gmail", "github", "other"]
    arguments: dict
    execution_result: dict
    execution_status: str
    verification_result: dict
    verification_status: Literal["pending", "pass", "retry", "fail"]
    feedback: str
    retry_count: int
    final_response: str


async def classification_agent(state: GraphState):
    classification = await invoke_structured("classifier", state["message"])
    service_mapping = {"gmail-task": "gmail", "github-task": "github", "other": "other"}
    return {
        "intent": classification.intent,
        "service": service_mapping[classification.type],
        "arguments": classification.arguments,
    }


async def verification_agent(state: GraphState):
    # Send only the data needed for verification. Credentials and user IDs stay out of the prompt.
    details = {
        "request": state["message"],
        "service": state["service"],
        "intent": state["intent"],
        "execution_result": state["execution_result"],
        "execution_status": state["execution_status"],
    }
    verification = await invoke_structured("verifier", json.dumps(details))
    failed = verification.status != "pass"
    retry_count = state["retry_count"] + int(failed)
    terminal_failure = verification.status == "fail" or failed and retry_count >= MAX_ATTEMPTS
    response = (verification.final_response or "").strip()
    if terminal_failure:
        response = "I could not verify the mock task. Please try again later."
    elif not response:
        response = (
            "The mock task finished, but I could not prepare a detailed response."
            if not failed else "I could not verify the mock task."
        )
    return {
        "feedback": verification.feedback,
        "retry_count": retry_count,
        "verification_result": verification.verification_result,
        "verification_status": verification.status,
        "execution_status": "failed" if terminal_failure else state["execution_status"],
        "final_response": response,
    }


def mock_github_task(state: GraphState):
    logger.info("Mock GitHub task executed")
    return {"execution_status": "completed", "execution_result": {
        "message": "GitHub mock task executed; no GitHub action was performed. "
                   "I can read notifications; say 'summarize my GitHub notifications'."}}


def mock_gmail_task(state: GraphState):
    logger.info("Mock Gmail task executed")
    return {"execution_status": "completed", "execution_result": {
        "message": "Gmail mock task executed; no email action was performed. "
                   "I can read inbox headers; say 'show my unread Gmail inbox'."}}


def other_task(state: GraphState):
    return {
        "execution_status": "unsupported",
        "final_response": (
            "I don't have a real action for that request yet. I can run read-only "
            "workflows such as a daily briefing, Gmail inbox headers, Drive metadata, "
            "Calendar events, and GitHub notifications. Ask 'what can you do?' for the "
            "current list."
        ),
    }


def route_task(state: GraphState):
    return state["service"]


def verify_cycle(state: GraphState) -> Literal["github", "gmail", "end"]:
    if state["verification_status"] == "retry" and state["retry_count"] < MAX_ATTEMPTS:
        return state["service"]
    return "end"
