"""Left navigation sidebar for the ChronoFace shell."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.ui.icons import app_icon, icon_pixmap
from src.ui.theme import SIDEBAR_ACTIVE, SIDEBAR_BG, SIDEBAR_HOVER
from src.utils.paths import app_icon_png

# Em space between button icon and label (QPushButton has no icon-gap QSS).
_ICON_TEXT_GAP = "\u2003"


def _brand_pixmap(logical_size: int = 28) -> QPixmap:
    """App mark at device DPR without the white square frame from the PNG canvas."""
    path = app_icon_png()
    if not path.is_file():
        return icon_pixmap("logo-mark", size=logical_size, color="#FFFFFF")

    source = QImage(str(path))
    if source.isNull():
        return icon_pixmap("logo-mark", size=logical_size, color="#FFFFFF")

    screen = QGuiApplication.primaryScreen()
    dpr = max(1.0, float(screen.devicePixelRatio()) if screen else 1.0)
    # Work at a modest supersample so chroma-key stays cheap but edges stay clean.
    pixel = max(1, int(round(logical_size * dpr)))
    work = source.scaled(
        pixel * 2,
        pixel * 2,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QImage.Format.Format_ARGB32)

    buf = memoryview(work.bits())
    for i in range(0, work.sizeInBytes(), 4):
        b, g, r = buf[i], buf[i + 1], buf[i + 2]
        if r > 240 and g > 240 and b > 240:
            buf[i + 3] = 0

    scaled = QPixmap.fromImage(
        work.scaled(
            pixel,
            pixel,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )
    scaled.setDevicePixelRatio(dpr)
    return scaled


class _NavButton(QPushButton):
    def __init__(self, title: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(f"{_ICON_TEXT_GAP}{title}", parent)
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icon_name = icon_name
        self.setIcon(app_icon(icon_name, size=18, color="#CBD5E1"))
        self.setIconSize(QSize(18, 18))
        self.setStyleSheet(
            "QPushButton#navButton {"
            "  text-align: left;"
            "  padding: 10px 14px;"
            "  border: none;"
            "  border-radius: 10px;"
            "  background: transparent;"
            "  color: #E2E8F0;"
            "  font-weight: 600;"
            "  font-size: 13px;"
            "}"
            "QPushButton#navButton:hover {"
            f"  background: {SIDEBAR_HOVER};"
            "}"
            "QPushButton#navButton:checked {"
            f"  background: {SIDEBAR_ACTIVE};"
            "  color: #FFFFFF;"
            "}"
        )

    def set_active_visual(self, active: bool) -> None:
        self.setIcon(
            app_icon(
                self._icon_name,
                size=18,
                color="#FFFFFF" if active else "#CBD5E1",
            )
        )


class AppSidebar(QWidget):
    """Dark navy navigation: Dashboard / Projects / Settings."""

    navigate = Signal(str)  # "dashboard" | "projects" | "settings"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("appSidebar")
        self.setFixedWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#appSidebar {{ background: {SIDEBAR_BG}; }}"
        )

        brand_icon = QLabel()
        brand_icon.setFixedSize(28, 28)
        brand_icon.setStyleSheet("background: transparent; border: none;")
        brand_icon.setPixmap(_brand_pixmap(28))

        brand_text = QLabel("ChronoFace")
        brand_text.setStyleSheet(
            "color: #FFFFFF; font-size: 16px; font-weight: 700; background: transparent; border: none;"
        )

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(4, 0, 4, 0)
        brand_row.setSpacing(10)
        brand_row.addWidget(brand_icon)
        brand_row.addWidget(brand_text)
        brand_row.addStretch(1)

        self._dashboard_btn = _NavButton("Dashboard", "layout-dashboard")
        self._projects_btn = _NavButton("Projects", "folder")
        self._settings_btn = _NavButton("Settings", "settings")

        self._nav_buttons = {
            "dashboard": self._dashboard_btn,
            "projects": self._projects_btn,
            "settings": self._settings_btn,
        }
        self._dashboard_btn.clicked.connect(lambda: self._on_nav("dashboard"))
        self._projects_btn.clicked.connect(lambda: self._on_nav("projects"))
        self._settings_btn.clicked.connect(lambda: self._on_nav("settings"))

        privacy = QFrame()
        privacy.setObjectName("privacyCard")
        privacy.setStyleSheet(
            "QFrame#privacyCard {"
            "  background: rgba(30, 41, 59, 0.85);"
            "  border: 1px solid rgba(148, 163, 184, 0.25);"
            "  border-radius: 12px;"
            "}"
            "QLabel { background: transparent; color: #CBD5E1; font-size: 11px; }"
        )
        shield = QLabel()
        shield.setPixmap(icon_pixmap("shield", size=18, color="#93C5FD"))
        privacy_title = QLabel("All analysis is local")
        privacy_title.setStyleSheet(
            "color: #F8FAFC; font-weight: 700; font-size: 12px; background: transparent;"
        )
        privacy_body = QLabel("Photos never leave your computer")
        privacy_body.setWordWrap(True)
        privacy_layout = QVBoxLayout(privacy)
        privacy_layout.setContentsMargins(12, 12, 12, 12)
        privacy_layout.setSpacing(6)
        privacy_layout.addWidget(shield)
        privacy_layout.addWidget(privacy_title)
        privacy_layout.addWidget(privacy_body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(brand_row)
        layout.addSpacing(24)
        layout.addWidget(self._dashboard_btn)
        layout.addWidget(self._projects_btn)
        layout.addWidget(self._settings_btn)
        layout.addStretch(1)
        layout.addWidget(privacy)

        self.set_active("projects")

    def set_active(self, key: str) -> None:
        for name, button in self._nav_buttons.items():
            active = name == key
            button.setChecked(active)
            button.set_active_visual(active)

    def set_dashboard_enabled(self, enabled: bool) -> None:
        self._dashboard_btn.setEnabled(enabled)
        if not enabled and self._dashboard_btn.isChecked():
            self.set_active("projects")

    def _on_nav(self, key: str) -> None:
        if key == "dashboard" and not self._dashboard_btn.isEnabled():
            return
        self.set_active(key)
        self.navigate.emit(key)
