"""Local scheduler worker that dispatches durable jobs through Runtime."""

import argparse
import asyncio

from orchestration.config import load_environment
from orchestration.runtime import Runtime
from orchestration.scheduler import dispatch_due


async def run_worker(once: bool = False, poll_seconds: int = 15) -> None:
    if poll_seconds < 1:
        raise ValueError("Poll interval must be positive")
    service = Runtime()
    while True:
        await dispatch_due(service.schedules, service)
        if once:
            return
        await asyncio.sleep(poll_seconds)


def main() -> None:
    load_environment()
    parser = argparse.ArgumentParser(description="Run due Orin schedules")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args()
    try:
        asyncio.run(run_worker(args.once, args.poll_seconds))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
