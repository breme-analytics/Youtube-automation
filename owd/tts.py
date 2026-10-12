"""Narration with Kokoro-82M (Apache-2.0): a script in, audio plus word timings out.

Kokoro sounds best on chunks of roughly 100-200 phonemes; it gets weak on very short utterances
and rushes very long ones (VOICES.md in hexgrad/Kokoro-82M). So the script is cut into sentence
groups of about that size, blank lines between paragraphs become pauses, and the word timings
Kokoro reports inside each chunk are moved onto the narration's clock for captions and cuts.

Kokoro and torch load on first use, so the text helpers here import quickly (and in tests).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np

from owd.config import SAMPLE_RATE
from owd.words import Word, save_words

# American (a) or British (b) English, female (f) or male (m): af_heart, bm_george, ...
VOICE_RE = re.compile(r"^[ab][fm]_[a-z]+$")

TARGET_CHARS = 260  # pack sentences into chunks up to this long
HARD_MAX_CHARS = 340  # a short sentence may stretch a chunk this far rather than stand alone
MIN_CHARS = 60  # chunks shorter than this sound clipped
SENTENCE_PAUSE = 0.12  # seconds of silence after a chunk that ends mid-paragraph
PARAGRAPH_PAUSE = 0.55
BEAT_PAUSE = 1.1  # "[pause]" in a script: a held beat before a reveal (Mario Joos: silence builds tension)
_BEAT = re.compile(r"\s*\[(?:pause|beat)\]\s*", re.I)

_ABBREVIATIONS = frozenset(
    {"mr", "mrs", "ms", "dr", "st", "mt", "vs", "etc", "e.g", "i.e", "jr", "sr", "no", "vol", "ch", "pp", "cf"}
)
_BOUNDARY = re.compile(r"[.!?…]+[\"”’')\]_]*\s+")  # "_" closes Project Gutenberg's _italics_
_CLAUSE = re.compile(r"(?<=[,;:—–])\s+")
_PARAGRAPH = re.compile(r"\n\s*\n")


def split_sentences(text: str) -> list[str]:
    """Sentences of `text`, whitespace collapsed. Initials ("Charles F. Haanel") and common
    abbreviations ("Dr.") don't end a sentence."""
    text = " ".join(text.split())
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        mark = match.group()
        if mark.startswith(".") and not mark.startswith(".."):
            before = text[start : match.start()].split()
            word = before[-1].lstrip("\"“‘'([").lower() if before else ""
            if word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
                continue
        sentences.append(text[start : match.end()].strip())
        start = match.end()
    if text[start:].strip():
        sentences.append(text[start:].strip())
    return sentences


def _split_long(sentence: str) -> list[str]:
    """A sentence over HARD_MAX_CHARS, cut at clause punctuation, or at spaces if it has none."""
    if len(sentence) <= HARD_MAX_CHARS:
        return [sentence]
    clauses: list[str] = []
    for clause in _CLAUSE.split(sentence):
        if clauses and len(clauses[-1]) + 1 + len(clause) <= TARGET_CHARS:
            clauses[-1] += " " + clause
        else:
            clauses.append(clause)
    parts: list[str] = []
    for clause in clauses:
        while len(clause) > HARD_MAX_CHARS:
            cut = clause.rfind(" ", 0, TARGET_CHARS)
            if cut <= 0:
                break  # one enormous token; Kokoro truncates it at its own limit
            parts.append(clause[:cut])
            clause = clause[cut + 1 :]
        parts.append(clause)
    return parts


def _pack(pieces: list[str]) -> list[str]:
    """Greedy packing up to TARGET_CHARS. A chunk still under MIN_CHARS may take the next piece up
    to HARD_MAX_CHARS, and a short last chunk joins the one before it, so nothing sounds clipped."""
    groups: list[str] = []
    for piece in pieces:
        if groups:
            joined = len(groups[-1]) + 1 + len(piece)
            if joined <= TARGET_CHARS or (len(groups[-1]) < MIN_CHARS and joined <= HARD_MAX_CHARS):
                groups[-1] += " " + piece
                continue
        groups.append(piece)
    if len(groups) > 1 and len(groups[-1]) < MIN_CHARS and len(groups[-2]) + 1 + len(groups[-1]) <= HARD_MAX_CHARS:
        tail = groups.pop()
        groups[-1] += " " + tail
    return groups


@dataclass(frozen=True)
class Chunk:
    text: str
    pause_after: float  # seconds of silence after it
    quote: int = 0  # 0 for narration, else the quote's number in the script (1, 2, ...)


def _quote_text(paragraph: str) -> str | None:
    """The quoted words if every line of the paragraph starts with ">", else None."""
    lines = [line.strip() for line in paragraph.strip().splitlines() if line.strip()]
    if not lines or not all(line.startswith(">") for line in lines):
        return None
    return " ".join(line[1:].strip() for line in lines)


def plan_chunks(script: str, first_quote: int = 1) -> list[Chunk]:
    """The script as Kokoro-sized chunks, each with the pause that follows it. Paragraphs whose
    lines start with ">" are quotes from the original book, numbered from `first_quote`. A
    "[pause]" inside a paragraph ends a chunk there and holds a beat of silence."""
    paragraphs = [p for p in _PARAGRAPH.split(script.strip()) if p.strip()]
    chunks: list[Chunk] = []
    quote_number = first_quote - 1
    for p_index, paragraph in enumerate(paragraphs):
        quoted = _quote_text(paragraph)
        if quoted is not None:
            quote_number += 1
        text = quoted if quoted is not None else paragraph
        segments = [s for s in _BEAT.split(text)] if quoted is None else [text]
        for s_index, segment in enumerate(segments):
            if not segment.strip():
                if chunks and s_index > 0:
                    chunks[-1] = Chunk(chunks[-1].text, max(chunks[-1].pause_after, BEAT_PAUSE), chunks[-1].quote)
                continue
            pieces = [part for sentence in split_sentences(segment) for part in _split_long(sentence)]
            groups = _pack(pieces)
            for g_index, group in enumerate(groups):
                if g_index < len(groups) - 1:
                    pause = SENTENCE_PAUSE
                elif s_index < len(segments) - 1:
                    pause = BEAT_PAUSE
                elif p_index < len(paragraphs) - 1:
                    pause = PARAGRAPH_PAUSE
                else:
                    pause = 0.0
                chunks.append(Chunk(group, pause, quote_number if quoted is not None else 0))
    return chunks


class Token(Protocol):
    """The parts of misaki's MToken used here."""

    text: str
    whitespace: str
    start_ts: float | None
    end_ts: float | None


def words_from_tokens(tokens: Iterable[Token], offset: float = 0.0, quote: int = 0) -> list[Word]:
    """Kokoro's tokens for one chunk as display words on the narration's clock.

    Tokens written without a space between them ("himself" + ";", "do" + "n't") make one word. A
    standalone punctuation mark ("—") joins the word before it. A word Kokoro couldn't time takes
    the end of the previous word, so it shows in captions without ever being highlighted.
    """
    groups: list[list[Token]] = []
    glue = False
    for token in tokens:
        if not token.text:
            continue
        if groups and glue:
            groups[-1].append(token)
        else:
            groups.append([token])
        glue = not token.whitespace

    words: list[Word] = []
    leading: list[str] = []  # punctuation before the chunk's first word
    for group in groups:
        text = "".join(token.text for token in group)
        if not any(char.isalnum() for char in text):
            if words:
                words[-1] = Word(f"{words[-1].text} {text}", words[-1].start, words[-1].end, quote)
            else:
                leading.append(text)
            continue
        if leading:
            text = " ".join([*leading, text])
            leading = []
        # Kokoro times punctuation too (as the pause it causes), so time the word by its letters.
        timed = [(t.start_ts, t.end_ts) for t in group if t.start_ts is not None and t.end_ts is not None]
        spoken = [
            (t.start_ts, t.end_ts)
            for t in group
            if t.start_ts is not None and t.end_ts is not None and any(char.isalnum() for char in t.text)
        ]
        timed = spoken or timed
        if timed:
            start = offset + min(s for s, _ in timed)
            end = offset + max(e for _, e in timed)
        else:
            start = end = words[-1].end if words else offset
        words.append(Word(text, round(start, 3), round(end, 3), quote))
    return words


@dataclass(frozen=True)
class Cast:
    """Who reads what: the narrator, and the voice for quotes from the original books."""

    narrator: str = "bm_george"
    narrator_speed: float = 1.0
    quote: str | None = None  # a second voice for book quotes; None: the narrator reads them (default)
    quote_speed: float = 0.95

    def __post_init__(self):
        for voice in (self.narrator, self.quote):
            if voice is not None and not VOICE_RE.match(voice):
                raise ValueError(f"Unknown voice {voice!r}: use an English Kokoro voice such as af_heart or bm_george")

    def voice_for(self, chunk: Chunk) -> tuple[str, float]:
        if chunk.quote and self.quote:
            return self.quote, self.quote_speed
        return self.narrator, self.narrator_speed

    @property
    def voices(self) -> list[str]:
        return [voice for voice in (self.narrator, self.quote) if voice]


@dataclass
class Narration:
    audio: np.ndarray  # mono float32 at sample_rate
    words: list[Word]
    cast: Cast
    sample_rate: int = SAMPLE_RATE

    @property
    def duration(self) -> float:
        return len(self.audio) / self.sample_rate

    def save(self, wav_path: Path | str, words_path: Path | str | None = None) -> None:
        import soundfile

        soundfile.write(str(wav_path), np.clip(self.audio, -1.0, 1.0), self.sample_rate, subtype="PCM_16")
        if words_path is not None:
            save_words(self.words, words_path, cast=asdict(self.cast), duration=round(self.duration, 3))


class Kokoro:
    """Kokoro-82M on the CPU, the same on a laptop and a cloud runner. Model files come from a
    pinned Hugging Face commit (owd.models), downloaded once (about 330 MB) and cached."""

    def __init__(self, device: str = "cpu"):
        self.device = device
        self._model = None
        self._pipelines: dict[str, object] = {}
        self._voice_files: dict[str, str] = {}

    def _pipeline(self, lang: str):
        from kokoro import KModel, KPipeline

        from owd.models import KOKORO_REPO, kokoro_files

        if self._model is None:
            config, weights = kokoro_files()
            self._model = KModel(repo_id=KOKORO_REPO, config=str(config), model=str(weights)).to(self.device).eval()
        if lang not in self._pipelines:
            self._pipelines[lang] = KPipeline(lang_code=lang, repo_id=KOKORO_REPO, model=self._model)
        return self._pipelines[lang]

    def _voice_file(self, voice: str) -> str:
        from owd.models import kokoro_voice

        if voice not in self._voice_files:
            self._voice_files[voice] = str(kokoro_voice(voice))  # a path, so Kokoro doesn't fetch "main"
        return self._voice_files[voice]

    def synthesize_chunks(self, chunks: Iterable[Chunk], cast: Cast, offset: float = 0.0) -> tuple[list[np.ndarray], list[Word]]:
        """Audio parts and timed words for `chunks`, timed from `offset` seconds."""
        parts: list[np.ndarray] = []
        words: list[Word] = []
        samples = round(offset * SAMPLE_RATE)
        for chunk in chunks:
            voice, speed = cast.voice_for(chunk)
            pipeline = self._pipeline(voice[0])
            for result in pipeline(chunk.text, voice=self._voice_file(voice), speed=speed, split_pattern=None):
                if result.audio is None:
                    continue
                audio = result.audio.detach().cpu().numpy().astype(np.float32).reshape(-1)
                words.extend(words_from_tokens(result.tokens or [], offset=samples / SAMPLE_RATE, quote=chunk.quote))
                parts.append(audio)
                samples += len(audio)
            gap = round(chunk.pause_after * SAMPLE_RATE)
            if gap:
                parts.append(np.zeros(gap, dtype=np.float32))
                samples += gap
        return parts, words

    def synthesize(self, script: str, cast: Cast | str = Cast(), speed: float | None = None) -> Narration:
        """Narrate `script`. `cast` may be a single voice name, which then reads everything."""
        if isinstance(cast, str):
            cast = Cast(narrator=cast, narrator_speed=speed or 1.0, quote=None)
        parts, words = self.synthesize_chunks(plan_chunks(script), cast)
        if not parts:
            raise ValueError("The script produced no speech")
        return Narration(np.concatenate(parts), words, cast)
