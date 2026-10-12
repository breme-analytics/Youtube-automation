# For development agents

Before changing anything, read:

1. `steering/instructions.md`: the owner's current instructions (they override defaults).
2. `docs/STATUS.md`: where things stand, what's proven, and the open decisions.
3. `docs/DEVLOG.md`: what has been built, why, and what's next.
4. `README.md` and `docs/GUIDE.md`: setup, commands, and how the owner uses the bot.

## Documentation rules (the owner's standing request: document everything)

In the same change as the work itself:

- **Every request or concern the owner raises** goes into `docs/REQUESTS.md`: the date, what she asked or raised
  (short, in her terms), what was done, where it's written up, and its status. Keep entries even if declined or
  replaced, and say why.
- **Every change** gets a `docs/DEVLOG.md` entry: what, why, and what was checked (and what wasn't).
- **Every caveat that affects the owner** (a limit, a risk, something that can fail) goes into `docs/DEPLOY.md`,
  "Caveats and fixes": what happens, what the bot does about it, and the fix.
- **`docs/STATUS.md` stays true:** what works and was checked, what's built but not proven, the gaps and
  decisions for the owner, and her checklist.
- **`docs/GUIDE.md`** changes whenever the way she controls the bot changes.
- Anything you tell the owner in chat that she'll need later belongs in one of these files.

## Rules

Keep the project reproducible: pin versions in `pyproject.toml`, re-lock with `uv lock`, and pin models in
`owd/models.py`. Never commit `.env` or keys. Nothing may cost money. Run
`uv run python -m pytest -q -m "slow or not slow"` before finishing.
