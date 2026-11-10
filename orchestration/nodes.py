from typing_extensions import TypedDict
from typing import Literal
from orchestration.agents import classifier, verifier


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
