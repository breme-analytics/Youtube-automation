"""Settings from the environment, with an optional .env file for local runs.

In CI and the cloud, secrets arrive as environment variables. Locally they can sit in .env (which
git ignores). A variable already set in the environment always wins over .env.
"""

from __future__ import annotations

import os
from pathlib import Path

from owd.config import ROOT


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if value[:1] in "\"'" and value[-1:] == value[:1] and len(value) >= 2:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key and key not in os.environ:
            os.environ[key] = value


def require(name: str) -> str:
    """An environment variable that must be set (from the environment or .env)."""
    load_dotenv()
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set. Add it to .env locally, or as a secret in CI.")
    return value
