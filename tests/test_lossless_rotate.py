"""Lossless rotation preserves dimensions swap and avoids JPEG re-encode loss."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from src.utils.lossless_rotate import RotateDirection, jpegtran_bin, rotate_image_lossless


def test_jpegtran_bundled() -> None:
    path = jpegtran_bin()
    assert path.is_file()


def test_jpeg_lossless_rotate_swaps_size_and_keeps_bytes_close(tmp_path: Path) -> None:
    src = tmp_path / "shot.jpg"
    # MCU-aligned size so jpegtran can transform perfectly.
    Image.new("RGB", (64, 48), color=(180, 40, 40)).save(src, format="JPEG", quality=92)
    before = src.read_bytes()
    before_size = src.stat().st_size

    rotate_image_lossless(src, RotateDirection.RIGHT, keep_timestamp=False)
    with Image.open(src) as image:
        assert image.size == (48, 64)
    after = src.read_bytes()
    # True DCT transform keeps size essentially identical (not a re-encode).
    assert abs(len(after) - before_size) <= 32
    assert after != before

    rotate_image_lossless(src, RotateDirection.LEFT, keep_timestamp=False)
    with Image.open(src) as image:
        assert image.size == (64, 48)


def test_png_rotate_is_pixel_exact(tmp_path: Path) -> None:
    src = tmp_path / "a.png"
    arr = np.zeros((20, 30, 3), dtype=np.uint8)
    arr[:, :, 0] = 10
    arr[0, 0] = (1, 2, 3)
    Image.fromarray(arr, mode="RGB").save(src)

    rotate_image_lossless(src, RotateDirection.RIGHT, keep_timestamp=False)
    with Image.open(src) as image:
        out = np.asarray(image)
    # CW 90: original (0,0) lands at (0, height-1) = (0, 29) in new coords? 
    # PIL ROTATE_270 (CW): pixel (x,y) -> (y, w-1-x)
    assert out.shape == (30, 20, 3)
    assert tuple(out[0, 19]) == (1, 2, 3)


def test_webp_lossless_rotate(tmp_path: Path) -> None:
    src = tmp_path / "a.webp"
    Image.new("RGB", (16, 24), color=(0, 120, 200)).save(
        src, format="WEBP", lossless=True
    )
    rotate_image_lossless(src, RotateDirection.LEFT, keep_timestamp=False)
    with Image.open(src) as image:
        assert image.size == (24, 16)


def test_keeps_mtime_when_requested(tmp_path: Path) -> None:
    src = tmp_path / "t.jpg"
    Image.new("RGB", (32, 32), color=(8, 8, 8)).save(src, format="JPEG", quality=90)
    mtime_ns = src.stat().st_mtime_ns
    rotate_image_lossless(src, RotateDirection.RIGHT, keep_timestamp=True)
    assert src.stat().st_mtime_ns == mtime_ns
