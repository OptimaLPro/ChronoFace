"""Startup welcome screen shown when no project is open."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
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


class WelcomeView(QWidget):
    """Clean startup screen: create a project or open a recent one."""

    create_project_requested = Signal()
    open_project_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

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
        self._recent_list.setMaximumWidth(560)
        self._recent_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._recent_list.setStyleSheet(
            "QListWidget {"
            "  border: 1px solid #ddd; background: white; padding: 4px;"
            "}"
            "QListWidget::item { padding: 10px 12px; }"
            "QListWidget::item:hover { background: #eef4ff; }"
            "QListWidget::item:selected { background: #d6e4ff; color: #111; }"
        )
        self._recent_list.itemActivated.connect(self._on_item_activated)
        self._recent_list.itemClicked.connect(self._on_item_activated)

        list_row = QHBoxLayout()
        list_row.addStretch(1)
        list_row.addWidget(self._recent_list, stretch=1)
        list_row.addStretch(1)

        content = QWidget()
        content.setMaximumWidth(640)
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(24, 24, 24, 24)
        content_layout.addStretch(1)
        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addSpacing(8)
        content_layout.addLayout(create_row)
        content_layout.addSpacing(16)
        content_layout.addWidget(self._recent_heading)
        content_layout.addWidget(self._empty_label)
        content_layout.addLayout(list_row, stretch=1)
        content_layout.addStretch(2)

        outer = QHBoxLayout(self)
        outer.addStretch(1)
        outer.addWidget(content, stretch=1)
        outer.addStretch(1)

        self.set_recent_projects([])

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
            label = name if not opened else f"{name}\nLast opened: {opened}"
            row = QListWidgetItem(label)
            row.setData(Qt.ItemDataRole.UserRole, str(item["id"]))
            row.setSizeHint(QSize(0, 52 if opened else 36))
            tip_parts = [name]
            if input_folder:
                tip_parts.append(input_folder)
            if opened:
                tip_parts.append(f"Last opened: {opened}")
            row.setToolTip("\n".join(tip_parts))
            self._recent_list.addItem(row)

    def _on_item_activated(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        project_id = item.data(Qt.ItemDataRole.UserRole)
        if project_id:
            self.open_project_requested.emit(str(project_id))
