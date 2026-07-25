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

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.ui.splash_screen import StartupSplash
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

    splash = StartupSplash()
    splash.center_on_screen()
    splash.show()
    app.processEvents()

    # Keep a strong ref so the splash is not GC'd before fade-out finishes.
    app._chronoface_splash = splash  # type: ignore[attr-defined]

    def boot() -> None:
        try:
            splash.set_status("Loading interface…")
            app.processEvents()

            # Heavy UI / vision imports happen here — after the splash is visible.
            from src.ui.main_window import MainWindow

            splash.set_status("Preparing workspace…")
            app.processEvents()

            window = MainWindow()
            if not icon.isNull():
                window.setWindowIcon(icon)
            # Keep the main window alive for the app lifetime.
            app._chronoface_window = window  # type: ignore[attr-defined]
            splash.finish_with(window)
        except Exception:
            splash.close()
            raise

    # Let the splash paint and start animating before the heavy boot work.
    QTimer.singleShot(60, boot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
