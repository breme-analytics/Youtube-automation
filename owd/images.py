"""AI-made still images for scenes that stock footage can't show (an idea, a moment from a book,
a feeling), from free services, tried in order:

1. Cloudflare Workers AI, FLUX.2 [klein] 4B. Needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_AI_TOKEN.
   It fits in the free 10,000 neurons a day for a video's worth of images.
2. Pollinations (image.pollinations.ai). Free and needs no key; slower, small watermark corner
   that the render crops away.

Every image is cached by its prompt, so re-rendering a video costs nothing. Images are painterly
on purpose: realistic AI pictures of real people or events must never appear (YouTube's rules).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import httpx
from PIL import Image

from owd.env import load_dotenv

CLOUDFLARE_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
CLOUDFLARE_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/" + CLOUDFLARE_MODEL
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"
STYLE = ("cinematic painterly illustration, oil painting texture, dramatic chiaroscuro lighting, deep blues and warm "
         "amber, atmospheric haze, no text, no letters, no watermark, no realistic faces")
WIDTH, HEIGHT = 1344, 768  # asked of FLUX on Cloudflare; Pollinations answers at about 1024x576
POLLINATIONS_CROP_BOTTOM = 0.07  # the share of the height holding Pollinations' corner mark
MIN_WIDTH = 900  # smaller answers are refused rather than blown up into a blurry frame


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
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = lambda message: None,
        providers: tuple[str, ...] = ("cloudflare", "pollinations"),
    ):
        if env is None:
            load_dotenv()
            env = dict(os.environ)
        self.cache_dir = Path(cache_dir)
        self.http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=180.0), follow_redirects=True)
        self.sleep, self.log = sleep, log
        account, token = (env.get("CLOUDFLARE_ACCOUNT_ID") or "").strip(), (env.get("CLOUDFLARE_AI_TOKEN") or "").strip()
        self._cloudflare = (account, token) if account and token else None
        self.providers = [p for p in providers if p != "cloudflare" or self._cloudflare]
        self._dead: set[str] = set()

    def _key(self, prompt: str, seed: int) -> str:
        return hashlib.sha1(json.dumps([prompt, seed, WIDTH, HEIGHT, STYLE]).encode()).hexdigest()[:20]

    def generate(self, prompt: str, seed: int = 0) -> Generated:
        """A PNG for `prompt` in the channel's style (from the cache when it was made before)."""
        key = self._key(prompt, seed)
        for provider in ("cloudflare", "pollinations"):
            cached = self.cache_dir / f"{key}-{provider}.png"
            if cached.is_file():
                return Generated(cached, provider)
        errors = []
        for provider in self.providers:
            if provider in self._dead:
                continue
            try:
                image = self._cloudflare_image(prompt, seed) if provider == "cloudflare" else self._pollinations(prompt, seed)
            except ImageError as error:
                errors.append(f"{provider}: {error}")
                self.log(f"image {provider}: {error}")
                continue
            path = self.cache_dir / f"{key}-{provider}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            image.convert("RGB").save(path)
            return Generated(path, provider)
        raise ImageError("no image service worked: " + " | ".join(errors))

    def _cloudflare_image(self, prompt: str, seed: int) -> Image.Image:
        account, token = self._cloudflare
        fields = {"prompt": f"{prompt}. {STYLE}", "width": str(WIDTH), "height": str(HEIGHT), "seed": str(seed)}
        try:
            response = self.http.post(CLOUDFLARE_URL.format(account=account), headers={"Authorization": f"Bearer {token}"},
                                      files={name: (None, value) for name, value in fields.items()})
        except httpx.HTTPError as error:
            raise ImageError(type(error).__name__) from None
        if response.status_code in (401, 403):
            self._dead.add("cloudflare")
            raise ImageError(f"HTTP {response.status_code}: the token needs Workers AI permission")
        if response.status_code == 429:
            self._dead.add("cloudflare")  # the day's free neurons are used up
            raise ImageError("daily free allowance used up (HTTP 429)")
        if response.status_code != 200:
            raise ImageError(f"HTTP {response.status_code}: {' '.join(response.text.split())[:160]}")
        body = response.json()
        data = (body.get("result") or {}).get("image") or body.get("image")
        if not data:
            raise ImageError("no image in the answer")
        return Image.open(io.BytesIO(base64.b64decode(data)))

    def _pollinations(self, prompt: str, seed: int) -> Image.Image:
        url = POLLINATIONS_URL.format(prompt=quote(f"{prompt}. {STYLE}", safe=""))
        params = {"width": WIDTH, "height": HEIGHT, "seed": seed, "nologo": "true", "model": "flux"}
        for attempt in range(3):
            try:
                response = self.http.get(url, params=params)
            except httpx.HTTPError as error:
                if attempt == 2:
                    raise ImageError(type(error).__name__) from None
                self.sleep(10)
                continue
            if response.status_code == 200 and response.headers.get("content-type", "").startswith("image"):
                image = Image.open(io.BytesIO(response.content))
                width, height = image.size
                if width < MIN_WIDTH:
                    raise ImageError(f"image too small ({width}x{height})")
                return image.crop((0, 0, width, round(height * (1 - POLLINATIONS_CROP_BOTTOM))))
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                self.sleep(15 * (attempt + 1))  # free and shared: wait, then try again
                continue
            raise ImageError(f"HTTP {response.status_code}")
        raise ImageError("no answer")
