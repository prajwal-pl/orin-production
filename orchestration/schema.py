from typing import Literal

from pydantic import BaseModel


class Classification(BaseModel):
    type: Literal["gmail-task", "github-task", "other"]
    intent: str
    arguments: dict


class Verifier(BaseModel):
    status: Literal["pass", "retry", "fail"]
    feedback: str
    verification_result: dict
    final_response: str | None
