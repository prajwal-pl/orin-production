"""Frozen entry point; the same FastAPI app serves desktop and browser clients."""

from orchestration.control_center import main


if __name__ == "__main__":
    main()
