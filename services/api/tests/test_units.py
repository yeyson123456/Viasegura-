"""Pure unit tests: detector post-processing, images, storage names and geodesy."""

import io

import numpy as np
import pytest
from PIL import Image

from app.services.detector import decode, letterbox, nms
from app.services.geo import haversine_m, line_length_km, meters_to_radians
from app.services.images import InvalidImageError, decode_image, encode_jpeg
from app.services.storage import LocalMediaStorage, check_name


def test_letterbox_keeps_aspect_ratio_and_pads() -> None:
    tensor, scale, (pad_x, pad_y) = letterbox(Image.new("RGB", (1280, 720), (255, 0, 0)), 640)

    assert tensor.shape == (1, 3, 640, 640)
    assert scale == pytest.approx(0.5)
    assert (pad_x, pad_y) == (0, 140)
    assert tensor[0, 0, 0, 0] == pytest.approx(114 / 255)  # padding
    assert tensor[0, 0, 320, 320] == pytest.approx(1.0)  # red image content


def test_nms_suppresses_overlaps_only() -> None:
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)

    assert nms(boxes, scores, 0.5) == [0, 2]


def test_decode_end2end_filters_by_confidence() -> None:
    output = np.array([[[10, 10, 50, 50, 0.9, 1], [0, 0, 5, 5, 0.1, 0]]], dtype=np.float32)

    rows = decode(output, "end2end", 0.25)

    assert rows.tolist() == [[10, 10, 50, 50, pytest.approx(0.9), 1]]


def test_decode_raw_layout_converts_and_applies_class_aware_nms() -> None:
    # raw: (1, 4 + classes, anchors) with [cx, cy, w, h, score_pothole, score_obstacle]
    anchors = np.array(
        [
            [100, 100, 20, 20, 0.90, 0.05],  # pothole
            [101, 101, 20, 20, 0.80, 0.05],  # duplicate pothole -> suppressed
            [101, 101, 20, 20, 0.05, 0.70],  # obstacle at same place -> kept (other class)
            [300, 300, 20, 20, 0.10, 0.10],  # below threshold
        ],
        dtype=np.float32,
    )
    rows = decode(anchors.T[None], "raw", 0.25)

    assert rows.shape == (2, 6)
    assert rows[0].tolist() == pytest.approx([90, 90, 110, 110, 0.9, 0])
    assert rows[1][5] == 1


def test_encode_jpeg_drops_exif_and_downscales() -> None:
    exif = Image.Exif()
    exif[0x010F] = "Maker"
    buffer = io.BytesIO()
    Image.new("RGB", (1600, 1200)).save(buffer, "JPEG", exif=exif.tobytes())

    out = Image.open(io.BytesIO(encode_jpeg(decode_image(buffer.getvalue()), max_side=640)))

    assert max(out.size) == 640
    assert dict(out.getexif()) == {}


def test_decode_image_rejects_garbage() -> None:
    with pytest.raises(InvalidImageError):
        decode_image(b"definitely not an image")


@pytest.mark.parametrize(
    "name", ["../secret.jpg", "/etc/passwd.jpg", "reports/../../x.jpg", "a.png", "UPPER.jpg"]
)
def test_media_names_reject_traversal_and_odd_names(name: str) -> None:
    with pytest.raises(ValueError, match="invalid media name"):
        check_name(name)


async def test_local_storage_round_trip(tmp_path) -> None:
    storage = LocalMediaStorage(tmp_path)

    await storage.save("reports/2026/11/20/abc-123.jpg", b"jpeg-bytes", "image/jpeg")

    assert await storage.load("reports/2026/11/20/abc-123.jpg") == b"jpeg-bytes"
    assert await storage.load("reports/2026/11/20/missing.jpg") is None


def test_geodesy_helpers() -> None:
    # One degree of latitude is ~111.2 km.
    assert haversine_m(-76.0, -9.0, -76.0, -10.0) == pytest.approx(111_195, rel=0.002)
    assert line_length_km([(-76.0, -9.0), (-76.0, -9.5), (-76.0, -10.0)]) == pytest.approx(
        111.2, rel=0.002
    )
    assert meters_to_radians(6_378_100) == pytest.approx(1.0)
