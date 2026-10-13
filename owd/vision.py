"""Does the picture match the words? A free vision model looks at a few candidate stock clips (one
still each) next to the sentence being narrated, and scores how well each one SHOWS it.

Pixabay's tags say what is in a clip ("candle"), not what it means, so tag matching alone gives
clips that are on topic but off message (a cosy Christmas candle under a sentence about despair).
This check fixes that. It runs on Gemini Flash-Lite's free tier (about 15 requests a minute and a
few hundred a day; a video needs about 50) and returns nothing if no vision model answers, in
which case the renderer falls back to tag matching.
"""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass
from typing import Callable, Sequence

import httpx
from PIL import Image

from owd.llm import extract_json

VISION_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MIN_INTERVAL = 4.5  # seconds between calls: about 13 a minute, under the free per-minute limit
GOOD_ENOUGH = 6  # a clip needs at least this score (0-10) to be shown
BUSY = (500, 502, 503, 504)  # the model is overloaded: worth one more try
BUSY_WAIT = 10.0


@dataclass(frozen=True)
class Verdict:
    scores: tuple[int, ...]  # 0-10 per candidate, in the order given
    reason: str = ""

    def ranked(self, minimum: int = GOOD_ENOUGH) -> list[int]:
        """Indexes of the candidates scoring at least `minimum`, best first."""
        order = sorted(range(len(self.scores)), key=lambda i: (-self.scores[i], i))
        return [i for i in order if self.scores[i] >= minimum]


def thumbnail_bytes(image: bytes, size: int = 384) -> bytes:
    """A small JPEG of `image`: plenty for the model to judge, cheap to send."""
    picture = Image.open(io.BytesIO(image)).convert("RGB")
    picture.thumbnail((size, size))
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=80)
    return out.getvalue()


PROMPT = """You choose B-roll for a calm, cinematic YouTube documentary about old books on the mind.
The narrator is saying: "{narration}"
The scene is meant to show: {intent}

Above are {count} candidate stills, numbered 1 to {count}. Score each from 0 to 10 for how well it SHOWS what the
narration means, in mood as well as subject: 10 is a perfect match, 6 is acceptable, below 6 would distract.
Score low anything that contradicts the narration (a festive or cheerful picture under a dark sentence), people
posing as in an advert, animals, text or logos, and anything that looks cheap.

Answer with JSON only: {{"scores": [<one score per still, in order>], "reason": "<at most 12 words about the best one>"}}"""


class VisionJudge:
    def __init__(
        self,
        api_key: str | None,
        *,
        http: httpx.Client | None = None,
        log: Callable[[str], None] = lambda message: None,
        models: Sequence[str] = VISION_MODELS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.key = (api_key or "").strip()
        self.http = http or httpx.Client(timeout=httpx.Timeout(20.0, read=90.0))
        self.log = log
        self.models = list(models)
        self.clock, self.sleep = clock, sleep
        self.calls = 0
        self.enabled = bool(self.key)
        self._last = -1e9

    def _pace(self) -> None:
        wait = MIN_INTERVAL - (self.clock() - self._last)
        if wait > 0:
            self.sleep(wait)
        self._last = self.clock()

    def judge(self, narration: str, intent: str, stills: Sequence[bytes]) -> Verdict | None:
        """Scores for `stills` (JPEG bytes), or None if no vision model could answer."""
        if not self.enabled or not stills:
            return None
        parts: list[dict] = []
        for number, still in enumerate(stills, start=1):
            parts.append({"text": f"Still {number}:"})
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(still).decode()}})
        parts.append({"text": PROMPT.format(narration=" ".join(narration.split())[:600], intent=intent, count=len(stills))})
        body = {"contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
        for model in list(self.models):
            for attempt in range(2):
                self._pace()
                try:
                    response = self.http.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": self.key}, json=body)
                except httpx.HTTPError as error:
                    self.log(f"vision {model}: {type(error).__name__}")
                    break
                self.calls += 1
                if response.status_code == 429 and attempt == 0:
                    self.log(f"vision {model}: rate limited; waiting a minute")
                    self.sleep(60)  # usually the per-minute limit
                    continue
                if response.status_code == 429:
                    self.log(f"vision {model}: limit reached for today")
                    self.models.remove(model)
                    break
                if response.status_code in (401, 403):
                    self.enabled = False
                    self.log("vision: the Gemini key was refused; using tag matching only")
                    return None
                if response.status_code in BUSY and attempt == 0:
                    self.log(f"vision {model}: busy (HTTP {response.status_code}); trying again in {BUSY_WAIT:g}s")
                    self.sleep(BUSY_WAIT)  # overloads usually pass within seconds
                    continue
                if response.status_code != 200:
                    self.log(f"vision {model}: HTTP {response.status_code}")
                    break
                verdict = self._parse(response, len(stills))
                if verdict is None:
                    self.log(f"vision {model}: unreadable answer")
                    break
                return verdict
        if not self.models:
            self.enabled = False
        return None

    @staticmethod
    def _parse(response: httpx.Response, count: int) -> Verdict | None:
        try:
            candidates = response.json().get("candidates") or []
            text = "".join(p.get("text", "") for p in (candidates[0].get("content") or {}).get("parts", []))
            text = text.strip()
            if text.startswith("[") and text.endswith("]"):
                text = text[1:-1]
            data = extract_json(text)
            scores = tuple(max(0, min(10, int(round(float(s))))) for s in data.get("scores", []))
        except (IndexError, ValueError, TypeError, AttributeError):
            return None
        if len(scores) != count:
            return None
        return Verdict(scores, str(data.get("reason", ""))[:120])
