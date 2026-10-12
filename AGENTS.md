# For development agents

Before changing anything, read:

1. `steering/instructions.md`: the owner's current instructions (they override defaults).
2. `docs/DEVLOG.md`: what has been built, why, and what's next. Add an entry for every change you make.
3. `README.md`: setup and commands.

Rules: keep the project reproducible (pin versions in `pyproject.toml`, re-lock with `uv lock`,
pin models in `owd/models.py`); never commit `.env` or keys; run `uv run python -m pytest -q`
before finishing.
