"""Channel settings from channel.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

from owd.config import ROOT
from owd.tts import Cast

CHANNEL_FILE = ROOT / "channel.toml"


def load_settings(path: Path = CHANNEL_FILE) -> dict:
    with Path(path).open("rb") as handle:
        return tomllib.load(handle)


def load_cast(path: Path = CHANNEL_FILE) -> Cast:
    voices = load_settings(path).get("voices", {})
    return Cast(
        narrator=voices.get("narrator", Cast.narrator),
        narrator_speed=float(voices.get("narrator_speed", Cast.narrator_speed)),
        quote=voices.get("quote") or None,
        quote_speed=float(voices.get("quote_speed", Cast.quote_speed)),
    )
