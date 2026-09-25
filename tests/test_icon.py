import base64
from io import BytesIO

import pytest

Image = pytest.importorskip("PIL.Image")

from discord_hq.server import icon  # noqa: E402

SPEC = {"letter": "K", "color": (241, 196, 15), "background": (18, 18, 20)}


def _decode(data_uri):
    return Image.open(BytesIO(base64.b64decode(data_uri.split(",", 1)[1])))


def test_icon_is_a_512px_png_data_uri():
    data_uri = icon.icon_data_uri(SPEC)
    assert data_uri.startswith("data:image/png;base64,")
    image = _decode(data_uri)
    assert image.format == "PNG"
    assert image.size == (512, 512)


def test_icon_uses_the_background_color():
    image = _decode(icon.icon_data_uri(SPEC)).convert("RGB")
    assert image.getpixel((5, 5)) == (18, 18, 20)
