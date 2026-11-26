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


class NotificationSummary(BaseModel):
    summary: str


class PlannerDecision(BaseModel):
    action: Literal["execute", "clarify", "refuse"]
    workflow: str | None = None
    message: str | None = None
