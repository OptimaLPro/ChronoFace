"""Lucide-style SVG icon loader for ChronoFace (HiDPI-aware)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from src.utils.paths import assets_dir


def icons_dir() -> Path:
    return assets_dir() / "icons"


def _svg_path(name: str) -> Path:
    return icons_dir() / f"{name}.svg"


def _device_pixel_ratio() -> float:
    app = QGuiApplication.instance()
    if app is None:
        return 1.0
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 1.0
    return max(1.0, float(screen.devicePixelRatio()))


@lru_cache(maxsize=256)
def _tinted_svg_bytes(name: str, color: str) -> bytes:
    path = _svg_path(name)
    if not path.is_file():
        return b""
    text = path.read_text(encoding="utf-8")
    for old in ("#FFFFFF", "#ffffff", "#1F2937", "#6B7280", "currentColor"):
        text = text.replace(f'stroke="{old}"', f'stroke="{color}"')
    return text.encode("utf-8")


def _render_svg_pixmap(
    name: str,
    *,
    logical_size: int,
    color: str,
    dpr: float,
) -> QPixmap:
    pixel_size = max(1, int(round(logical_size * dpr)))
    data = _tinted_svg_bytes(name, color)
    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    if data:
        renderer = QSvgRenderer(QByteArray(data))
        if renderer.isValid():
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            renderer.render(painter, QRectF(0, 0, pixel_size, pixel_size))
            painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def icon_pixmap(
    name: str,
    *,
    size: int = 20,
    color: str = "#FFFFFF",
) -> QPixmap:
    """Render a named SVG icon at the current display DPR for sharp output."""
    return _render_svg_pixmap(
        name,
        logical_size=size,
        color=color,
        dpr=_device_pixel_ratio(),
    )


def app_icon(name: str, *, size: int = 20, color: str = "#FFFFFF") -> QIcon:
    """Return a QIcon with native and 2x pixmaps for crisp toolbar buttons."""
    icon = QIcon()
    dpr = _device_pixel_ratio()
    icon.addPixmap(_render_svg_pixmap(name, logical_size=size, color=color, dpr=dpr))
    if dpr < 1.75:
        icon.addPixmap(
            _render_svg_pixmap(name, logical_size=size, color=color, dpr=2.0)
        )
    return icon


def icon_size(size: int = 20) -> QSize:
    return QSize(size, size)
