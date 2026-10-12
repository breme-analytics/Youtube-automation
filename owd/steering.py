"""The owner's steering: steering/instructions.md plus every .md file in steering/references/.

Read before every script is written and placed in the writer's instructions, above the bot's own
defaults. Files in references/off/ are ignored, so a reference can be switched off by moving it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from owd.config import ROOT

STEERING_DIR = ROOT / "steering"
MAX_CHARS = 40_000  # keeps prompts well inside every free model's context


@dataclass(frozen=True)
class Steering:
    instructions: str
    references: tuple[tuple[str, str], ...]  # (file name, text)
    warnings: tuple[str, ...] = ()

    def as_prompt(self) -> str:
        parts = ["OWNER INSTRUCTIONS (follow these over your own defaults):", self.instructions.strip() or "(none)"]
        for name, text in self.references:
            parts += ["", f"REFERENCE: references/{name}", text.strip()]
        return "\n".join(parts)


def load_steering(folder: Path = STEERING_DIR, max_chars: int = MAX_CHARS) -> Steering:
    folder = Path(folder)
    instructions_file = folder / "instructions.md"
    instructions = instructions_file.read_text(encoding="utf-8") if instructions_file.is_file() else ""
    references: list[tuple[str, str]] = []
    warnings: list[str] = []
    used = len(instructions)
    for path in sorted((folder / "references").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if used + len(text) > max_chars:
            warnings.append(f"Skipped references/{path.name}: steering is over {max_chars} characters")
            continue
        references.append((path.name, text))
        used += len(text)
    return Steering(instructions, tuple(references), tuple(warnings))
