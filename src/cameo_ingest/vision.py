"""What a vision model is sent: images within its pixel budget (`config.IMAGE_PIXELS`), their
sides in whole patches of 48 x 48 px, the patches gemma-4 sees (FU-015). Sketches are drawn to
the budget (`sketch.canvas`); other images are scaled down to it (`fit_image`)."""

from __future__ import annotations

import io
import logging

log = logging.getLogger(__name__)

PATCH_PX = 48


def patch_sides(w: float, h: float) -> tuple[int, int]:
    """A w x h px picture's sides cut down to whole patches, at least one each."""
    return max(PATCH_PX, int(w // PATCH_PX) * PATCH_PX), max(PATCH_PX, int(h // PATCH_PX) * PATCH_PX)


def fit_image(data: bytes, mime: str, pixels: int) -> tuple[bytes, str, dict | None]:
    """The image scaled down to at most `pixels`, sides in whole patches, as PNG; unchanged if
    it already fits or can't be read."""
    from PIL import Image  # only when an image is sent

    try:
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
            if w * h <= pixels:
                return data, mime, None
            f = (pixels / (w * h)) ** 0.5
            size = patch_sides(w * f, h * f)
            buf = io.BytesIO()
            img.convert("RGB").resize(size, Image.LANCZOS).save(buf, "PNG")
            return buf.getvalue(), "image/png", {"from": [w, h], "to": list(size)}
    except Exception as e:  # a damaged or unusual image is sent as it is
        log.debug("cannot scale an image: %s", e)
        return data, mime, None
