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

from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.utils.logging import setup_logging


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("ChronoFace")
    app.setApplicationDisplayName("ChronoFace")
    app.setOrganizationName("ChronoFace")
    app.setOrganizationDomain("chronoface.local")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
