"""Credential-free Phase 3 memory and skill adoption demonstration."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from orchestration import runtime
from orchestration.runtime import Runtime


def crowded_notifications() -> list[dict]:
    fixture = json.loads((Path(__file__).parent / "fixtures" / "learning_v1.json").read_text())
    repository = fixture["repository"]
    items = [{"repository": repository, "title": f"Review {index}",
              "reason": "review_requested", "url": f"https://github.com/{repository}/pull/{index}"}
             for index in range(fixture["review_request_count"])]
    items.append({"repository": repository, "title": fixture["security_title"],
                  "reason": "security_alert", "url": fixture["security_url"]})
    return items


async def benchmark() -> dict:
    with TemporaryDirectory() as directory, patch.dict("os.environ", {
        "ORIN_DATABASE_PATH": str(Path(directory) / "orin.db"),
        "ORIN_GITHUB_ALLOWED_USERS": "local", "ORIN_MODEL": "scripted:primary",
        "ORIN_FALLBACK_MODEL": "", "ORIN_TASK_MODEL_CALLS": "0",
    }), patch.object(runtime, "fetch_notifications", AsyncMock(return_value=crowded_notifications())):
        service = Runtime(Path(directory) / "orin.db")
        async def run(session: str) -> dict:
            task = await service.submit("local", session, "Summarize my GitHub notifications")
            return await service.run("local", task["id"])

        baseline = await run("baseline")
        proposal = next(skill for skill in service.skills.list("local") if skill["kind"] == "learned")
        builtin = next(skill for skill in service.skills.list("local") if skill["kind"] == "builtin")
        service.skills.correction("local", baseline["id"], "Security alert was missing")
        service.skills.activate("local", proposal["id"])
        adopted = await run("adopted")
        service.skills.activate("local", builtin["id"])
        rolled_back = await run("rolled-back")

        for category, content in [
            ("preference", "Prioritize security alerts"),
            ("semantic", "Review requests require attention"),
            ("working", "Gmail inbox status"),
        ]:
            service.memory.add("local", category, content, "benchmark fixture")
        queries = [("security alerts", "Prioritize security alerts"),
                   ("review requests", "Review requests require attention"),
                   ("gmail inbox", "Gmail inbox status")]
        relevance = sum(service.memory.search("local", query, 1)[0]["content"] == expected
                        for query, expected in queries)
        metrics = service.skills.metrics("local")
        return {
            "fixture_version": 1,
            "validation": json.loads(proposal["evaluation"]),
            "end_to_end": {
                "baseline_security_visible": "Security alert" in baseline["result"],
                "adopted_security_visible": "Security alert" in adopted["result"],
                "rollback_security_visible": "Security alert" in rolled_back["result"],
                "all_tasks_completed": all(task["status"] == "completed" for task in
                                           (baseline, adopted, rolled_back)),
            },
            "memory_top1_relevance": {"correct": relevance, "total": len(queries)},
            "observed_skill_metrics": metrics,
            "measurement_note": "Synthetic notifications and lexical queries; no provider calls or neural embeddings.",
        }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(benchmark()), indent=2))
