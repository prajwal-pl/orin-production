from langgraph.graph import StateGraph, START, END
from src.nodes import GraphState
from src.nodes import (
    classification_agent,
    mock_github_task,
    mock_gmail_task,
    verification_agent,
    route_task,
)

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
