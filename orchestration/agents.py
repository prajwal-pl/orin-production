"""Model configuration and structured agent calls for the prototype."""

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy

from orchestration.schema import Classification, Verifier

load_dotenv()

DEFAULT_MODEL = "openrouter:nvidia/nemotron-3.5-lightning:free"
PROMPTS = {
    "classifier": (
        "Classify the user's request as gmail-task, github-task, or other. "
        "Extract intent and task arguments. The Gmail and GitHub actions are mock demonstrations."
    ),
    "verifier": (
        "Review the request and execution outcome. Return status pass, retry, or fail. "
        "Use retry only for a recoverable verification problem and fail for a terminal problem. "
        "feedback, a verification_result dictionary, and a user-facing final_response. "
        "A canned mock result is only evidence that the mock ran, not that an external action happened."
    ),
}
SCHEMAS = {"classifier": Classification, "verifier": Verifier}


def configured_models() -> list[str]:
    primary = os.getenv("ORIN_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    fallback = os.getenv("ORIN_FALLBACK_MODEL", "").strip()
    return [primary, fallback] if fallback and fallback != primary else [primary]


@lru_cache(maxsize=8)
def build_agent(role: str, model: str):
    return create_agent(
        model=model,
        system_prompt=PROMPTS[role],
        tools=[],
        response_format=ToolStrategy(SCHEMAS[role]),
        name=f"Orin {role}",
    )


async def invoke_structured(role: str, message: str):
    """Try the optional backup model when the primary call fails."""
    last_error = None
    for model in configured_models():
        try:
            result = await build_agent(role, model).ainvoke(
                {"messages": [{"role": "user", "content": message}]}
            )
            response = result["structured_response"]
            return SCHEMAS[role].model_validate(response)
        except Exception as error:
            last_error = error
    raise RuntimeError(f"{role} model call failed") from last_error
