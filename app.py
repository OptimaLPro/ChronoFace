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
from src.utils.logging import setup_logging
from src.utils.paths import app_icon_png


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
    path = app_icon_png()
    if path.is_file():
        return QIcon(str(path))
    return QIcon()


def main() -> int:
    setup_logging()
    _configure_windows_taskbar_id()
    app = QApplication(sys.argv)
    app.setApplicationName("ChronoFace")
    app.setApplicationDisplayName("ChronoFace")
    app.setOrganizationName("ChronoFace")
    app.setOrganizationDomain("chronoface.local")
    app.setStyle("Fusion")

    icon = _load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
