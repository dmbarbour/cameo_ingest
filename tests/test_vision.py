"""Images sent to a vision model: within its pixel budget, sides in whole patches (FU-015)."""

import io

from PIL import Image

from cameo_ingest.config import IMAGE_PIXELS
from cameo_ingest.vision import fit_image


def png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, "PNG")
    return buf.getvalue()


def test_large_images_are_scaled_to_whole_patches():
    data, mime, scaled = fit_image(png(3000, 1000), "image/x-whatever", IMAGE_PIXELS)
    assert mime == "image/png" and scaled is not None and scaled["from"] == [3000, 1000]
    w, h = scaled["to"]
    assert w % 48 == 0 and h % 48 == 0 and w * h <= IMAGE_PIXELS and 2.5 < w / h < 3.5
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (w, h)
    small = png(100, 100)
    assert fit_image(small, "image/png", IMAGE_PIXELS) == (small, "image/png", None)
    assert fit_image(b"not an image", "image/gif", IMAGE_PIXELS) == (b"not an image", "image/gif", None)
