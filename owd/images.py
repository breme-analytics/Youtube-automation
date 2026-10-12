"""AI-made still images for scenes that stock footage can't show (an idea, a moment from a book,
a feeling): Cloudflare Workers AI, FLUX.2 [klein] 4B, inside its free allowance of 10,000 neurons a
day (about 40 paintings), with CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_AI_TOKEN.

Without the token, or once the day's allowance is used, there are no paintings: the renderer then
uses the best stock clip for the scene and flags it for review. (Pollinations, the old no-key
fallback, began charging for every image in October 2026, so it was removed: nothing here may cost
money.)

Every image is cached by its prompt, so re-rendering a video costs nothing. Images are painterly
on purpose: realistic AI pictures of real people or events must never appear (YouTube's rules).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx
from PIL import Image

from owd.env import load_dotenv

CLOUDFLARE_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
CLOUDFLARE_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/" + CLOUDFLARE_MODEL
STYLE = ("cinematic painterly illustration, oil painting texture, dramatic chiaroscuro lighting, deep blues and warm "
         "amber, atmospheric haze, no text, no letters, no watermark, no realistic faces")
WIDTH, HEIGHT = 1344, 768  # 16:9-ish; scaled and cropped to 1920x1080 at render time


class ImageError(RuntimeError):
    pass


@dataclass(frozen=True)
class Generated:
    path: Path
    provider: str


class SceneImages:
    def __init__(
        self,
        cache_dir: Path,
        *,
        env: dict[str, str] | None = None,
        http: httpx.Client | None = None,
        log: Callable[[str], None] = lambda message: None,
    ):
        if env is None:
            load_dotenv()
            env = dict(os.environ)
        self.cache_dir = Path(cache_dir)
        self.http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=180.0))
        self.log = log
        account, token = (env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip(), (env.get("CLOUDFLARE_AI_TOKEN") or "").strip()
        self._cloudflare = (account, token) if account and token else None
        self.available = self._cloudflare is not None
        self.reason = "" if self.available else "CLOUDFLARE_AI_TOKEN is not set"

    def _key(self, prompt: str, seed: int) -> str:
        return hashlib.sha1(json.dumps([prompt, seed, WIDTH, HEIGHT, STYLE]).encode()).hexdigest()[:20]

    def generate(self, prompt: str, seed: int = 0) -> Generated:
        """A PNG for `prompt` in the channel's style (from the cache when it was made before)."""
        cached = self.cache_dir / f"{self._key(prompt, seed)}-cloudflare.png"
        if cached.is_file():
            return Generated(cached, "cloudflare")
        if not self.available:
            raise ImageError(self.reason)
        image = self._cloudflare_image(prompt, seed)
        cached.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(cached)
        return Generated(cached, "cloudflare")

    def _stop(self, reason: str) -> ImageError:
        self.available, self.reason = False, reason
        self.log(f"paintings: {reason}")
        return ImageError(reason)

    def _cloudflare_image(self, prompt: str, seed: int) -> Image.Image:
        account, token = self._cloudflare
        fields = {"prompt": f"{prompt}. {STYLE}", "width": str(WIDTH), "height": str(HEIGHT), "seed": str(seed)}
        try:
            response = self.http.post(CLOUDFLARE_URL.format(account=account), headers={"Authorization": f"Bearer {token}"},
                                      files={name: (None, value) for name, value in fields.items()})
        except httpx.HTTPError as error:
            raise ImageError(type(error).__name__) from None
        if response.status_code in (401, 403):
            raise self._stop(f"Cloudflare refused the token (HTTP {response.status_code}): it needs Workers AI permission")
        if response.status_code == 429 or "4006" in response.text:
            raise self._stop("today's free Cloudflare allowance is used up")
        if response.status_code != 200:
            raise ImageError(f"HTTP {response.status_code}: {' '.join(response.text.split())[:160]}")
        body = response.json()
        data = (body.get("result") or {}).get("image") or body.get("image")
        if not data:
            raise ImageError("no image in the answer")
        return Image.open(io.BytesIO(base64.b64decode(data)))
