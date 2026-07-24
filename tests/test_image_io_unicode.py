"""Tests for Unicode-safe image I/O (Windows Hebrew paths, etc.)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from src.utils.image_utils import read_image_bgr, write_image_bgr


def test_read_image_bgr_with_non_ascii_path(tmp_path: Path) -> None:
    folder = tmp_path / "תיקיית תמונות"
    folder.mkdir()
    path = folder / "אלונה.jpg"
    Image.new("RGB", (24, 24), color=(10, 20, 30)).save(path, format="JPEG")

    image = read_image_bgr(path)
    assert image is not None
    assert image.shape[0] == 24
    assert image.shape[1] == 24


def test_write_image_bgr_with_non_ascii_path(tmp_path: Path) -> None:
    folder = tmp_path / "פלט"
    out = folder / "crop.jpg"
    image = np.zeros((16, 16, 3), dtype=np.uint8)
    image[:] = (5, 15, 25)
    write_image_bgr(out, image)
    assert out.is_file()
    loaded = read_image_bgr(out)
    assert loaded.shape == (16, 16, 3)
