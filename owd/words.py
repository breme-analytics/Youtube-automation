"""Word timings: the link between the narration, the captions and the scene cuts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Word:
    text: str  # as written in the script, punctuation attached ("himself.")
    start: float  # seconds from the start of the narration
    end: float
    quote: int = 0  # 0 for the narrator's own words, else which quote (1, 2, ...) this word is from


def save_words(words: Iterable[Word], path: Path | str, **meta) -> None:
    payload = {**meta, "words": [asdict(word) for word in words]}
    Path(path).write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")


def load_words(path: Path | str) -> list[Word]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Word(**word) for word in payload["words"]]
