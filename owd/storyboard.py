"""A storyboard: everything one video says and shows, as TOML so people and the script writer can
both produce and edit it.

    title = "The mistake that keeps your mind full of weeds"
    format = "long"                      # "long" (default) or "short"
    alt_titles = ["...", "..."]          # other title options, for testing
    thumbnail_text = "Weeds grow anyway"
    thumbnail_accent = ["weeds"]
    description = "..."

    [[sources]]                          # books quoted; every quote is checked against them
    file = "sources/as-a-man-thinketh.txt"
    cite = "James Allen, As a Man Thinketh (1903)"

    [[research]]                         # studies the script mentions (linked in the description)
    id = "R1"
    title = "..."
    link = "https://..."

    [[claims]]                           # factual claims, listed for the owner to check
    claim = "..."
    basis = "R1"                         # a research id, "book" or "general"

    [[scene]]
    chapter = "The garden nobody tends"  # starts a new chapter (and a YouTube chapter)
    visual = "old book pages"            # stock footage search
    text = '''
    A hundred years ago...
    '''

In `text`, a paragraph whose lines start with ">" is a quote from a source, shown on screen as
it's read. Everything else is the narrator's own words.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from owd.config import ROOT

FORMATS = ("short", "long")


@dataclass(frozen=True)
class Scene:
    visual: str
    text: str
    category: str | None = None
    chapter: str | None = None  # set on the first scene of each chapter


@dataclass(frozen=True)
class Source:
    file: Path
    cite: str


@dataclass(frozen=True)
class Research:
    id: str
    title: str
    link: str
    source: str = ""


@dataclass(frozen=True)
class Claim:
    claim: str
    basis: str


@dataclass(frozen=True)
class Storyboard:
    title: str
    format: str
    scenes: tuple[Scene, ...]
    thumbnail_text: str = ""
    thumbnail_accent: tuple[str, ...] = ()
    description: str = ""
    sources: tuple[Source, ...] = field(default=())
    alt_titles: tuple[str, ...] = ()
    research: tuple[Research, ...] = ()
    claims: tuple[Claim, ...] = ()

    @property
    def script(self) -> str:
        return "\n\n".join(scene.text.strip() for scene in self.scenes)

    def chapter_starts(self) -> list[tuple[int, str]]:
        """(scene index, title) for every chapter, in order."""
        return [(index, scene.chapter) for index, scene in enumerate(self.scenes) if scene.chapter]


def parse_storyboard(data: dict, base: Path = ROOT) -> Storyboard:
    problems: list[str] = []
    title = str(data.get("title", "")).strip()
    if not title:
        problems.append("title is missing")
    video_format = str(data.get("format", "long")).strip()
    if video_format not in FORMATS:
        problems.append(f"format must be one of {FORMATS}, not {video_format!r}")
    scenes = []
    for index, raw in enumerate(data.get("scene", []), start=1):
        visual, text = str(raw.get("visual", "")).strip(), str(raw.get("text", "")).strip()
        if not visual:
            problems.append(f"scene {index} has no visual")
        if not text:
            problems.append(f"scene {index} has no text")
        category, chapter = raw.get("category"), raw.get("chapter")
        scenes.append(Scene(visual, text, str(category).strip() if category else None,
                            str(chapter).strip() if chapter else None))
    if not scenes:
        problems.append("there are no [[scene]] entries")
    sources = []
    for raw in data.get("sources", []):
        path = Path(str(raw.get("file", "")))
        path = path if path.is_absolute() else base / path
        if not path.is_file():
            problems.append(f"source file not found: {path}")
        sources.append(Source(path, str(raw.get("cite", "")).strip()))
    research = tuple(Research(str(r.get("id", "")), str(r.get("title", "")), str(r.get("link", "")),
                              str(r.get("source", ""))) for r in data.get("research", []))
    claims = tuple(Claim(str(c.get("claim", "")), str(c.get("basis", ""))) for c in data.get("claims", []))
    if problems:
        raise ValueError("Storyboard problems: " + "; ".join(problems))
    return Storyboard(
        title=title,
        format=video_format,
        scenes=tuple(scenes),
        thumbnail_text=str(data.get("thumbnail_text", "")).strip(),
        thumbnail_accent=tuple(str(word) for word in data.get("thumbnail_accent", [])),
        description=str(data.get("description", "")).strip(),
        sources=tuple(sources),
        alt_titles=tuple(str(t) for t in data.get("alt_titles", [])),
        research=research,
        claims=claims,
    )


def load_storyboard(path: Path | str) -> Storyboard:
    path = Path(path)
    with path.open("rb") as handle:
        return parse_storyboard(tomllib.load(handle), base=ROOT)


def _string(value: str) -> str:
    """A TOML string: a readable multi-line literal where possible, else a basic string. (A JSON
    string is a valid TOML basic string: TOML accepts all of JSON's escapes but none it can't read.)"""
    if "\n" in value and "'''" not in value and not value.endswith("'") and all(
        ch == "\n" or ch == "\t" or ord(ch) >= 0x20 for ch in value
    ):
        return "'''\n" + value + "\n'''"
    return json.dumps(value, ensure_ascii=False)


def _list(values) -> str:
    return "[" + ", ".join(_string(str(v)) for v in values) + "]"


def _relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def dump_storyboard(board: Storyboard, header: str = "") -> str:
    """TOML text for `board`, which load_storyboard reads back to the same storyboard."""
    lines = [f"# {line}" if line else "#" for line in header.splitlines()]
    lines += [
        f"title = {_string(board.title)}",
        f"format = {_string(board.format)}",
        f"alt_titles = {_list(board.alt_titles)}",
        f"thumbnail_text = {_string(board.thumbnail_text)}",
        f"thumbnail_accent = {_list(board.thumbnail_accent)}",
        f"description = {_string(board.description)}",
    ]
    for source in board.sources:
        lines += ["", "[[sources]]", f"file = {_string(_relative(source.file))}", f"cite = {_string(source.cite)}"]
    for item in board.research:
        lines += ["", "[[research]]", f"id = {_string(item.id)}", f"title = {_string(item.title)}",
                  f"link = {_string(item.link)}", f"source = {_string(item.source)}"]
    for claim in board.claims:
        lines += ["", "[[claims]]", f"claim = {_string(claim.claim)}", f"basis = {_string(claim.basis)}"]
    for scene in board.scenes:
        lines += ["", "[[scene]]"]
        if scene.chapter:
            lines.append(f"chapter = {_string(scene.chapter)}")
        lines.append(f"visual = {_string(scene.visual)}")
        if scene.category:
            lines.append(f"category = {_string(scene.category)}")
        lines.append(f"text = {_string(scene.text if chr(10) in scene.text else scene.text + chr(10))}")
    return "\n".join(lines) + "\n"
