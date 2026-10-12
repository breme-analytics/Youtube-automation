"""Backgrounds drawn in code, with no image service: a soft glow in a dark sky with faint stars
and film grain. Used in tests and demos, and as the fallback when image generation fails."""

from __future__ import annotations

import numpy as np
from PIL import Image

# (sky, glow) colours
PALETTES = {
    "dawn": ((10, 8, 30), (255, 176, 82)),
    "violet": ((12, 6, 28), (190, 120, 255)),
    "teal": ((4, 16, 24), (90, 220, 210)),
    "ember": ((18, 6, 6), (255, 110, 60)),
}


def glow_background(
    size: tuple[int, int],
    *,
    palette: str = "dawn",
    seed: int = 0,
    center: tuple[float, float] | None = None,
    stars: bool = True,
) -> Image.Image:
    rng = np.random.default_rng(seed)
    width, height = size
    sky, glow = (np.array(colour, dtype=np.float32) for colour in PALETTES[palette])
    cx, cy = center if center is not None else (rng.uniform(0.3, 0.7), rng.uniform(0.25, 0.55))

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    scale = max(width, height)
    distance = np.hypot(xx - cx * width, yy - cy * height) / scale
    light = 0.72 * np.exp(-((distance / 0.22) ** 2)) + 0.28 * np.exp(-((distance / 0.6) ** 2))
    for _ in range(2):  # faint drifting haze, so no two frames share one shape
        bx, by = rng.uniform(0.1, 0.9) * width, rng.uniform(0.1, 0.9) * height
        haze = np.hypot(xx - bx, yy - by) / scale
        light += rng.uniform(0.08, 0.18) * np.exp(-((haze / rng.uniform(0.15, 0.35)) ** 2))
    light /= light.max()  # rescale rather than clip: clipping leaves a flat disc with a hard edge
    image = sky + (glow - sky) * light[..., None]

    edge = ((xx / width - 0.5) ** 2 + (yy / height - 0.5) ** 2) * 2  # 0 at the centre, 1 at the corners
    image *= (1.0 - 0.45 * np.clip(edge, 0.0, 1.0))[..., None]

    if stars:
        count = width * height // 2500
        sx, sy = rng.integers(0, width, count), rng.integers(0, height, count)
        brightness = 40 + 215 * rng.random(count) ** 4  # mostly faint, a few bright
        image[sy, sx] = np.maximum(image[sy, sx], brightness[:, None])

    # Light grain stops gradients banding after compression; heavier grain bloats the file.
    image += rng.normal(0.0, 1.5, image.shape)
    return Image.fromarray(np.clip(image, 0, 255).astype(np.uint8), "RGB")
