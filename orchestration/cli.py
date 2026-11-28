"""Local CLI using the shared task runtime."""

import argparse
import asyncio
import os

from orchestration.config import load_environment
from orchestration.runtime import Runtime, task_reply


async def run_command(request: str, session_id: str):
    load_environment()
    service = Runtime()
    owner = os.getenv("ORIN_CLI_USER", "local")
    task = await service.submit(owner, session_id, request)
    result = await service.run(owner, task["id"])
    print(task_reply(result))


async def resume_command(task_id: str):
    load_environment()
    service = Runtime()
    owner = os.getenv("ORIN_CLI_USER", "local")
    result = await service.run(owner, task_id)
    print(task_reply(result))


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
