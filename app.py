"""
ChronoFace — application entry point.

Run from the project root:

    python app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path when launched as a script.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.ui.theme import load_app_stylesheet
from src.utils.logging import setup_logging
from src.utils.paths import app_icon_ico, app_icon_png


def _configure_windows_taskbar_id() -> None:
    """Group the process under ChronoFace in the Windows taskbar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            "ChronoFace.ChronoFace"
        )
    except Exception:
        pass


def _load_app_icon() -> QIcon:
    """Build a multi-size icon so Windows taskbar/title bar stay crisp."""
    icon = QIcon()
    # Prefer .ico on Windows — it carries 16–256px sizes the taskbar needs.
    ico = app_icon_ico()
    if ico.is_file():
        icon.addFile(str(ico))
    png = app_icon_png()
    if png.is_file():
        icon.addFile(str(png))
    return icon


def main() -> int:
    setup_logging()
    _configure_windows_taskbar_id()
    app = QApplication(sys.argv)
    app.setApplicationName("ChronoFace")
    app.setApplicationDisplayName("ChronoFace")
    app.setOrganizationName("ChronoFace")
    app.setOrganizationDomain("chronoface.local")
    app.setStyle("Fusion")
    app.setStyleSheet(load_app_stylesheet())

    icon = _load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MainWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
