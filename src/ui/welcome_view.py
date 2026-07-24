"""Startup welcome screen shown when no project is open."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.utils.paths import app_icon_png


class _ElidedLabel(QLabel):
    """Single-line label that truncates with an ellipsis when too narrow."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setText(text)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._elide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        metrics = self.fontMetrics()
        self.setText(
            metrics.elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                max(0, self.width()),
            )
        )


class WelcomeView(QWidget):
    """Clean startup screen: create a project or open a recent one."""

    create_project_requested = Signal()
    open_project_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._privacy_banner = QLabel(
            "All photo analysis is performed locally on this computer.\n"
            "No photos or facial data are uploaded."
        )
        self._privacy_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._privacy_banner.setWordWrap(True)
        self._privacy_banner.setStyleSheet(
            "QLabel { background: #eef6ee; border: 1px solid #b7d7b7; "
            "padding: 10px; color: #1f4d1f; font-weight: 600; }"
        )

        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedHeight(104)
        icon_path = app_icon_png()
        if icon_path.is_file():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                self._icon_label.setPixmap(
                    pixmap.scaled(
                        96,
                        96,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        else:
            self._icon_label.hide()

        title = QLabel("ChronoFace")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        subtitle = QLabel(
            "Sort a folder of photos by the age of a specific person.\n"
            "Create a new project or open one you used recently."
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #444; font-size: 13px;")

        self._create_button = QPushButton("Create New Project")
        self._create_button.setMinimumHeight(40)
        self._create_button.setMinimumWidth(220)
        self._create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_button.setStyleSheet(
            "QPushButton {"
            "  font-size: 14px; font-weight: 600; padding: 10px 24px;"
            "  background: #2f6fed; color: white; border: none; border-radius: 6px;"
            "}"
            "QPushButton:hover { background: #2558c7; }"
            "QPushButton:pressed { background: #1e4aa8; }"
        )
        self._create_button.clicked.connect(self.create_project_requested.emit)

        create_row = QHBoxLayout()
        create_row.addStretch(1)
        create_row.addWidget(self._create_button)
        create_row.addStretch(1)

        self._recent_heading = QLabel("Recent projects")
        self._recent_heading.setStyleSheet(
            "font-size: 14px; font-weight: 600; margin-top: 8px;"
        )

        self._empty_label = QLabel(
            "No recent projects yet. Create a new project to get started."
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet("color: #666; padding: 16px;")

        self._recent_list = QListWidget()
        self._recent_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._recent_list.setAlternatingRowColors(True)
        self._recent_list.setMinimumHeight(180)
        self._recent_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._recent_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._recent_list.setStyleSheet(
            "QListWidget {"
            "  border: 1px solid #ddd; background: white; padding: 4px;"
            "}"
            "QListWidget::item { padding: 0; }"
            "QListWidget::item:hover { background: #eef4ff; }"
            "QListWidget::item:selected { background: #d6e4ff; color: #111; }"
        )
        self._recent_list.itemActivated.connect(self._on_item_activated)
        self._recent_list.itemClicked.connect(self._on_item_activated)

        content = QWidget()
        content.setMaximumWidth(640)
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.addStretch(1)
        content_layout.addWidget(self._icon_label)
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addSpacing(8)
        content_layout.addLayout(create_row)
        content_layout.addSpacing(16)
        content_layout.addWidget(self._recent_heading)
        content_layout.addWidget(self._empty_label)
        content_layout.addWidget(self._recent_list, stretch=1)
        content_layout.addStretch(2)

        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(content, stretch=1)
        center.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(self._privacy_banner)
        outer.addLayout(center, stretch=1)

        self.set_recent_projects([])

    def set_privacy_banner_visible(self, visible: bool) -> None:
        """Show or hide the privacy notice on this welcome screen."""
        self._privacy_banner.setVisible(visible)

    def set_recent_projects(self, recent: list[dict]) -> None:
        """Populate the recent-projects list from repository rows."""
        self._recent_list.clear()
        has_recent = bool(recent)
        self._recent_list.setVisible(has_recent)
        self._empty_label.setVisible(not has_recent)
        self._recent_heading.setVisible(True)

        for item in recent:
            name = str(item.get("name") or "Untitled project")
            opened = str(item.get("last_opened_at") or "")
            input_folder = str(item.get("input_folder") or "")

            row = QListWidgetItem()
            row.setData(Qt.ItemDataRole.UserRole, str(item["id"]))
            row.setSizeHint(QSize(0, 44))
            tip_parts = [name]
            if input_folder:
                tip_parts.append(input_folder)
            if opened:
                tip_parts.append(f"Last opened: {opened}")
            row.setToolTip("\n".join(tip_parts))
            self._recent_list.addItem(row)
            self._recent_list.setItemWidget(row, self._build_row_widget(name, opened))

    def _build_row_widget(self, name: str, opened: str) -> QWidget:
        row_widget = QWidget()
        # Let list-item click/activation handle selection and open.
        row_widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        layout = QHBoxLayout(row_widget)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(16)

        name_label = _ElidedLabel(name)
        name_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #111;")

        opened_label = QLabel(opened)
        opened_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        opened_label.setStyleSheet("font-size: 12px; color: #666;")
        opened_label.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )

        layout.addWidget(name_label, stretch=1)
        layout.addWidget(opened_label, stretch=0)
        return row_widget

    def _on_item_activated(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        project_id = item.data(Qt.ItemDataRole.UserRole)
        if project_id:
            self.open_project_requested.emit(str(project_id))
