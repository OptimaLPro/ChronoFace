"""Discover supported image files in a folder tree."""

from __future__ import annotations

from pathlib import Path

from src.utils.image_utils import SUPPORTED_IMAGE_EXTENSIONS, is_supported_image
from src.utils.logging import get_logger

logger = get_logger("metadata.image_discovery")


def discover_images(
    root: Path,
    *,
    recursive: bool = True,
) -> list[Path]:
    """
    Return sorted unique paths to supported images under ``root``.

    Skips hidden directories (names starting with '.') and non-files.
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"Input folder is not a directory: {root}")

    found: list[Path] = []
    if recursive:
        iterator = root.rglob("*")
    else:
        iterator = root.glob("*")

    for path in iterator:
        try:
            if not path.is_file():
                continue
            # Skip files inside hidden directories (e.g. .cache)
            if any(part.startswith(".") for part in path.relative_to(root).parts[:-1]):
                continue
            if is_supported_image(path):
                found.append(path.resolve())
        except OSError as exc:
            logger.warning("Skipping path due to OS error: %s (%s)", path, exc)

    unique = sorted(set(found), key=lambda p: str(p).lower())
    logger.info(
        "Discovered %s supported images in %s (extensions=%s)",
        len(unique),
        root,
        sorted(SUPPORTED_IMAGE_EXTENSIONS),
    )
    return unique
