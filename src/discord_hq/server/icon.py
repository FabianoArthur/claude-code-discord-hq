"""Server icon: a one- or two-letter monogram, 512x512 PNG, sent as a data URI.
Needs the optional `icon` extra (Pillow)."""

from __future__ import annotations

import base64
from io import BytesIO

SIZE = 512
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int):
    from PIL import ImageFont

    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def icon_data_uri(spec: dict) -> str:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (SIZE, SIZE), tuple(spec["background"]))
    draw = ImageDraw.Draw(image)
    font = _font(int(SIZE * 0.55))
    left, top, right, bottom = draw.textbbox((0, 0), spec["letter"], font=font)
    position = ((SIZE - (right - left)) / 2 - left, (SIZE - (bottom - top)) / 2 - top)
    draw.text(position, spec["letter"], font=font, fill=tuple(spec["color"]))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
