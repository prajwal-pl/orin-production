from pydantic import BaseModel
from typing import Literal


class Classification(BaseModel):
    type: Literal["gmail-task", "github-task", "other"]
    intent: str
    arguments: dict


class Verifier(BaseModel):
    feedback: str
    retry_count: int
    verification_result: dict
    final_response: str | None
