"""Checks that narration says what the script says: transcribe it with faster-whisper and compare
word by word. Catches skipped, repeated and garbled words. Runs on any OS through pip, so it
doesn't depend on how ffmpeg was built."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from owd.config import tool
from owd.ffmpeg import FFmpegError


@lru_cache(maxsize=1)
def _whisper():
    from faster_whisper import WhisperModel

    from owd.models import whisper_dir

    return WhisperModel(str(whisper_dir()), device="cpu", compute_type="int8")


def _samples_16k(audio: Path | str) -> np.ndarray:
    """Mono float32 samples at 16 kHz, decoded by ffmpeg. faster-whisper 1.2.1's own decoder calls
    PyAV with an argument PyAV 19 removed, so it isn't used."""
    command = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-i", str(audio),
               "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    proc = subprocess.run(command, capture_output=True)
    if proc.returncode != 0:
        raise FFmpegError(command, proc.stderr.decode(errors="replace"))
    return np.frombuffer(proc.stdout, dtype=np.float32)


def transcribe(audio: Path | str) -> str:
    segments, _info = _whisper().transcribe(
        _samples_16k(audio), language="en", beam_size=5, condition_on_previous_text=False, vad_filter=False
    )
    return " ".join(" ".join(segment.text.split()) for segment in segments)


def _spelling(word: str) -> str:
    """British and American spellings as one form, since whisper writes American: armoury/armory,
    realise/realize, centre/center."""
    if len(word) > 4:
        word = word.replace("our", "or")
    word = re.sub(r"(?<=..)is(e|ed|es|ing)$", r"iz\1", word)
    word = re.sub(r"(?<=..)ys(e|ed|es|ing)$", r"yz\1", word)
    return re.sub(r"(?<=..)tre$", "ter", word)


# Names the speech recogniser spells another way, mapped to the form the scripts use.
SOUNDS_ALIKE = {"alan": "allen", "allan": "allen"}

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(n: int) -> list[str]:
    """0 to 9999 in words ("90" -> ["ninety"]); larger numbers stay as digits. Applied to both the
    script and the transcript, so "ninety percent" and "90%" count as the same words."""
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        tens, ones = divmod(n, 10)
        return [_TENS[tens - 2], *([_ONES[ones]] if ones else [])]
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return [_ONES[hundreds], "hundred", *(number_words(rest) if rest else [])]
    if n < 10_000:
        thousands, rest = divmod(n, 1000)
        return [*number_words(thousands), "thousand", *(number_words(rest) if rest else [])]
    return [str(n)]


def normalize(text: str) -> list[str]:
    """Lower-case words with punctuation removed, spelling unified, numbers spelled out and known
    name spellings mapped; hyphenated words count as separate words."""
    text = text.lower().replace("’", "'").replace("‘", "'").replace("%", " percent ")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,000 -> 1000
    text = re.sub(r"[-–—]", " ", text)
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    words: list[str] = []
    for word in text.split():
        word = word.strip("'")
        if not word:
            continue
        if word.isdigit():
            words.extend(number_words(int(word)))
        else:
            word = _spelling(word)
            words.append(SOUNDS_ALIKE.get(word, word))
    return words


@dataclass(frozen=True)
class Comparison:
    errors: int  # substitutions + deletions + insertions
    reference_words: int
    differences: list[tuple[str, str]]  # (script, heard); "" marks a missing or extra word

    @property
    def word_error_rate(self) -> float:
        return self.errors / max(self.reference_words, 1)


def compare(script: str, heard: str) -> Comparison:
    """Word-level edit distance between the script and the transcript, with the differing words."""
    ref, hyp = normalize(script), normalize(heard)
    rows, cols = len(ref) + 1, len(hyp) + 1
    cost = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        cost[i][0] = i
    for j in range(cols):
        cost[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            same = ref[i - 1] == hyp[j - 1]
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1, cost[i - 1][j - 1] + (0 if same else 1))
    differences: list[tuple[str, str]] = []
    i, j = len(ref), len(hyp)
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            if ref[i - 1] != hyp[j - 1]:
                differences.append((ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            differences.append((ref[i - 1], ""))
            i -= 1
        else:
            differences.append(("", hyp[j - 1]))
            j -= 1
    return Comparison(cost[-1][-1], len(ref), differences[::-1])
