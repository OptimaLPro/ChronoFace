"""Thumbnail generation and Unicode-safe image I/O helpers."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from src.utils.logging import get_logger

logger = get_logger("utils.image_utils")

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

DEFAULT_THUMBNAIL_SIZE = (256, 256)


def is_supported_image(path: Path) -> bool:
    """Return True if the path has a Phase-1/MVP supported image extension."""
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def read_image_bgr(path: Path | str) -> np.ndarray:
    """
    Read an image as a BGR numpy array.

    Uses ``np.fromfile`` + ``cv2.imdecode`` so Windows paths with non-ASCII
    characters (e.g. Hebrew folder names) work. Plain ``cv2.imread`` fails on
    those paths and returns None.
    """
    path = Path(path)
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError as exc:
        raise ValueError(f"Could not read image file: {path}") from exc
    if data.size == 0:
        raise ValueError(f"Image file is empty: {path}")
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not decode image: {path}")
    return image


def write_image_bgr(path: Path | str, image: np.ndarray) -> Path:
    """Write a BGR image with Unicode-safe path handling on Windows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower() or ".jpg"
    ok, buffer = cv2.imencode(suffix, image)
    if not ok:
        raise ValueError(f"Could not encode image for writing: {path}")
    buffer.tofile(str(path))
    return path


def create_thumbnail(
    source: Path,
    destination: Path,
    size: tuple[int, int] = DEFAULT_THUMBNAIL_SIZE,
) -> Path:
    """
    Create a JPEG thumbnail for ``source`` at ``destination``.

    Applies EXIF orientation. Never modifies the original file.
    Pillow handles Unicode paths correctly on Windows.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(size, Image.Resampling.LANCZOS)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            elif image.mode == "L":
                image = image.convert("RGB")
            image.save(destination, format="JPEG", quality=85, optimize=True)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise ValueError(f"Could not create thumbnail for {source}: {exc}") from exc

    return destination


def thumbnail_filename_for(file_hash: str) -> str:
    """Stable thumbnail filename keyed by content hash."""
    return f"{file_hash}.jpg"
