"""Model configuration and structured agent calls for the prototype."""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

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


@dataclass(frozen=True)
class ModelCapabilities:
    structured_output: bool
    tool_calling: bool | None


@dataclass(frozen=True)
class ProviderResult:
    model: str
    response: Classification | Verifier
    capabilities: ModelCapabilities
    input_tokens: int | None
    output_tokens: int | None


class ProviderCallError(RuntimeError):
    pass


class ModelBackend(Protocol):
    async def invoke(self, role: str, model: str, message: str) -> ProviderResult: ...


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


class LangChainBackend:
    async def invoke(self, role: str, model: str, message: str) -> ProviderResult:
        result = await build_agent(role, model).ainvoke(
            {"messages": [{"role": "user", "content": message}]}
        )
        response = SCHEMAS[role].model_validate(result["structured_response"])
        messages = result.get("messages") or []
        usage = getattr(messages[-1], "usage_metadata", None) if messages else None
        usage = usage or {}
        capabilities = ModelCapabilities(structured_output=True, tool_calling=None)
        return ProviderResult(model, response, capabilities,
                              usage.get("input_tokens"), usage.get("output_tokens"))


async def invoke_result(role: str, message: str, backend: ModelBackend | None = None) -> ProviderResult:
    """Normalize results and try the backup after a provider or schema error."""
    backend = backend or LangChainBackend()
    last_error = None
    for model in configured_models():
        try:
            return await backend.invoke(role, model, message)
        except Exception as error:
            last_error = error
    raise ProviderCallError(f"{role} model call failed") from last_error


async def invoke_structured(role: str, message: str):
    return (await invoke_result(role, message)).response
