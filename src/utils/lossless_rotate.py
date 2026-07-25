"""Lossless in-place photo rotation (JPEG DCT / PNG / WebP)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from enum import Enum
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from src.utils.logging import get_logger
from src.utils.paths import assets_dir

logger = get_logger("utils.lossless_rotate")


class RotateDirection(str, Enum):
    LEFT = "left"  # 90° counter-clockwise
    RIGHT = "right"  # 90° clockwise


_JPEG_EXTS = {".jpg", ".jpeg"}
_PNG_EXTS = {".png"}
_WEBP_EXTS = {".webp"}


class LosslessRotateError(ValueError):
    """Raised when a file cannot be rotated without quality loss."""


def jpegtran_bin() -> Path:
    """Return path to the bundled (or PATH) jpegtran executable."""
    bundled = assets_dir() / "bin" / ("jpegtran.exe" if sys.platform == "win32" else "jpegtran")
    if bundled.is_file():
        return bundled
    which = shutil.which("jpegtran")
    if which:
        return Path(which)
    raise LosslessRotateError(
        "jpegtran not found. Expected assets/bin/jpegtran "
        f"({'jpegtran.exe' if sys.platform == 'win32' else 'jpegtran'})."
    )


def rotate_image_lossless(
    path: Path | str,
    direction: RotateDirection | str,
    *,
    keep_timestamp: bool = True,
) -> Path:
    """
    Rotate ``path`` 90° in place with no quality loss.

    - JPEG: libjpeg-turbo ``jpegtran`` DCT block transform (same idea as
      JPEG Lossless Rotator).
    - PNG / WebP: decode → transpose → lossless re-encode (format-native).
    """
    path = Path(path)
    if not path.is_file():
        raise LosslessRotateError(f"File not found: {path}")

    direction = RotateDirection(direction)
    suffix = path.suffix.lower()
    mtime_ns = path.stat().st_mtime_ns if keep_timestamp else None

    if suffix in _JPEG_EXTS:
        _rotate_jpeg(path, direction)
    elif suffix in _PNG_EXTS:
        _rotate_raster(path, direction, format_name="PNG")
    elif suffix in _WEBP_EXTS:
        _rotate_raster(path, direction, format_name="WEBP")
    else:
        raise LosslessRotateError(
            f"Unsupported format for lossless rotate: {suffix or '(none)'}"
        )

    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def _jpegtran_degrees(direction: RotateDirection) -> int:
    # jpegtran -rotate N is clockwise degrees.
    return 90 if direction is RotateDirection.RIGHT else 270


def _rotate_jpeg(path: Path, direction: RotateDirection) -> None:
    jpegtran = jpegtran_bin()
    degrees = _jpegtran_degrees(direction)
    bin_dir = jpegtran.parent

    # jpegtran on Windows mishandles many non-ASCII paths — stage via ASCII temps.
    with tempfile.TemporaryDirectory(prefix="chronoface_rot_") as tmp:
        tmp_dir = Path(tmp)
        src_tmp = tmp_dir / "in.jpg"
        out_tmp = tmp_dir / "out.jpg"
        shutil.copy2(path, src_tmp)
        cmd = [
            str(jpegtran),
            "-rotate",
            str(degrees),
            "-copy",
            "all",
            "-outfile",
            str(out_tmp),
            str(src_tmp),
        ]
        completed = subprocess.run(
            cmd,
            cwd=str(bin_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0 or not out_tmp.is_file():
            detail = (completed.stderr or completed.stdout or "").strip()
            raise LosslessRotateError(
                f"jpegtran failed for {path.name}"
                + (f": {detail}" if detail else ".")
            )
        _atomic_replace(out_tmp, path)


def _rotate_raster(
    path: Path,
    direction: RotateDirection,
    *,
    format_name: str,
) -> None:
    transpose = (
        Image.Transpose.ROTATE_270
        if direction is RotateDirection.RIGHT
        else Image.Transpose.ROTATE_90
    )
    try:
        with Image.open(path) as image:
            # Bake current EXIF orientation, then rotate pixels, then clear tag.
            image = ImageOps.exif_transpose(image) or image
            rotated = image.transpose(transpose)
            save_kwargs: dict = {}
            if format_name == "WEBP":
                save_kwargs.update(lossless=True, method=6)
            elif format_name == "PNG":
                save_kwargs.update(optimize=True)
            # Drop stale Orientation so viewers don't double-apply.
            if "exif" in rotated.info:
                rotated.info = {k: v for k, v in rotated.info.items() if k != "exif"}

            fd, tmp_name = tempfile.mkstemp(
                prefix="chronoface_rot_",
                suffix=path.suffix.lower(),
                dir=str(path.parent),
            )
            os.close(fd)
            tmp_path = Path(tmp_name)
            try:
                rotated.save(tmp_path, format=format_name, **save_kwargs)
                _atomic_replace(tmp_path, path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise LosslessRotateError(f"Could not rotate {path.name}: {exc}") from exc


def _atomic_replace(src: Path, dest: Path) -> None:
    """Replace ``dest`` with ``src`` (same volume) as atomically as the OS allows."""
    try:
        os.replace(src, dest)
    except OSError:
        # Cross-device or locked: copy then remove.
        shutil.copy2(src, dest)
        src.unlink(missing_ok=True)
