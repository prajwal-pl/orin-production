"""Locate Orin's local environment file regardless of the launch directory.

GUI launches (the packaged desktop app) do not start in the repository root, so
relying on ``dotenv``'s current-directory default silently dropped every
credential. Resolve an explicit file, the stable user config file, the current
directory, and finally the source checkout so the desktop and browser
interfaces read the same configuration.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def config_dir() -> Path:
    """The stable local configuration directory, overridable for tests."""
    return Path(os.getenv("ORIN_CONFIG_DIR", "~/.orion/config")).expanduser()


def environment_files() -> list[Path]:
    """Candidate environment files in precedence order."""
    explicit = os.getenv("ORIN_ENV_FILE", "").strip()
    candidates = [Path(explicit)] if explicit else []
    candidates.extend([Path.cwd() / ".env", config_dir() / ".env", PROJECT_ROOT / ".env"])
    files: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            files.append(resolved)
    return files


def load_environment() -> Path | None:
    """Load the first available environment file without overriding the process env.

    Values already present in the environment always win, matching the previous
    ``load_dotenv`` behavior. Returns the file that was loaded, if any.
    """
    for path in environment_files():
        if path.is_file():
            load_dotenv(path, override=False)
            return path
    return None
