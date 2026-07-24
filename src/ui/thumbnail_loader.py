"""Load thumbnails safely on Windows paths with non-ASCII characters."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtGui import QImage, QPixmap

from src.utils.logging import get_logger

logger = get_logger("ui.thumbnail_loader")


def load_thumbnail_pixmap(
    path: Path | str | None,
    size: int = 140,
) -> QPixmap:
    """
    Return a QPixmap thumbnail.

    Uses Pillow so Hebrew/Unicode paths work (QPixmap(path) often fails on Windows).
    """
    if not path:
        return QPixmap()
    path = Path(path)
    if not path.is_file():
        return QPixmap()
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                image = image.convert("RGB")
            data = image.tobytes("raw", "RGB")
            qimage = QImage(
                data,
                image.width,
                image.height,
                image.width * 3,
                QImage.Format.Format_RGB888,
            )
            return QPixmap.fromImage(qimage.copy())
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        logger.debug("Thumbnail load failed for %s: %s", path, exc)
        return QPixmap()
