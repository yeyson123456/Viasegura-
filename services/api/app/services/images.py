"""Image decoding and privacy-safe re-encoding."""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

# Refuse decompression bombs well before Pillow's default limit.
Image.MAX_IMAGE_PIXELS = 25_000_000

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class InvalidImageError(ValueError):
    pass


def decode_image(data: bytes) -> Image.Image:
    """Decode an uploaded image (RGB, EXIF orientation applied) or raise InvalidImageError."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image) or image
        return image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise InvalidImageError(str(exc)) from exc


def encode_jpeg(image: Image.Image, max_side: int = 640, quality: int = 85) -> bytes:
    """Re-encode as a small JPEG. A fresh encode carries no EXIF/GPS metadata."""
    copy = image.copy()
    copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, "JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
