"""Local CLI using the shared task runtime."""

import argparse
import asyncio
import os

from dotenv import load_dotenv

from orchestration.runtime import Runtime


async def run_command(request: str, session_id: str):
    load_dotenv()
    service = Runtime()
    owner = os.getenv("ORIN_CLI_USER", "local")
    task = await service.submit(owner, session_id, request)
    result = await service.run(owner, task["id"])
    print(result["result"] or f"Task {result['id']} is {result['status']}. Resume with --resume {result['id']}")


async def resume_command(task_id: str):
    load_dotenv()
    service = Runtime()
    owner = os.getenv("ORIN_CLI_USER", "local")
    result = await service.run(owner, task_id)
    print(result["result"] or f"Task {task_id} is {result['status']}")


def main():
    parser = argparse.ArgumentParser(description="Run an Orin task")
    parser.add_argument("request", nargs="?")
    parser.add_argument("--session", default="cli")
    parser.add_argument("--resume")
    args = parser.parse_args()
    if args.resume:
        asyncio.run(resume_command(args.resume))
    elif args.request:
        asyncio.run(run_command(args.request, args.session))
    else:
        parser.error("Provide a request or --resume TASK_ID")


if __name__ == "__main__":
    main()
