"""Design tokens and QSS loading for the ChronoFace light theme."""

from __future__ import annotations

from pathlib import Path

from src.utils.paths import assets_dir

# Primary palette (light mode). Dark mode can swap these later.
PRIMARY = "#2F6BFF"
PRIMARY_HOVER = "#2558E0"
PRIMARY_PRESSED = "#1E4AC4"
BACKGROUND = "#F7F8FB"
CARD = "#FFFFFF"
BORDER = "#E5E7EB"
BORDER_SUBTLE = "#EEF0F4"
TEXT = "#1F2937"
TEXT_MUTED = "#6B7280"
TEXT_SOFT = "#9CA3AF"
SIDEBAR_BG = "#0F172A"
SIDEBAR_HOVER = "#1E293B"
SIDEBAR_ACTIVE = "#2F6BFF"
SUCCESS = "#16A34A"
WARNING = "#D97706"
ERROR = "#DC2626"
PURPLE = "#7C3AED"

AGE_BAND_COLORS = (
    ("0–2", "#3B82F6"),
    ("3–5", "#2563EB"),
    ("6–9", "#4F46E5"),
    ("10–13", "#6366F1"),
    ("14–17", "#7C3AED"),
    ("18–25", "#9333EA"),
    ("26+", "#A855F7"),
)

FONT_STACK = '"Segoe UI Variable", "Segoe UI", Inter, system-ui, sans-serif'

SPACING = 8


def theme_qss_path() -> Path:
    return assets_dir() / "theme" / "app.qss"


def load_app_stylesheet() -> str:
    """Return the global app QSS, including scrollbar rules."""
    from src.ui.style_utils import DEFAULT_SCROLLBAR_STYLE

    path = theme_qss_path()
    body = path.read_text(encoding="utf-8") if path.is_file() else ""
    check_icon = (assets_dir() / "icons" / "check.svg").resolve().as_posix()
    body = body.replace("__CHECK_ICON__", check_icon)
    return f"{body}\n{DEFAULT_SCROLLBAR_STYLE}"
