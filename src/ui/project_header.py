"""Dashboard project title row with primary actions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.domain.models import ProjectConfig
from src.utils.paths import open_in_file_manager


class ProjectHeader(QWidget):
    """Large project title, metadata subtitle, Edit + Export + Analyze CTAs."""

    edit_requested = Signal()
    export_requested = Signal()
    analyze_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._folder_path: Path | None = None

        self._title = QLabel("Project")
        self._title.setObjectName("titleLabel")

        self._subtitle_prefix = QLabel("")
        self._subtitle_prefix.setObjectName("mutedLabel")

        self._path_link = QLabel("")
        self._path_link.setObjectName("pathLinkLabel")
        self._path_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._path_link.setWordWrap(True)
        self._path_link.setTextFormat(Qt.TextFormat.RichText)
        self._path_link.setOpenExternalLinks(False)
        self._path_link.linkActivated.connect(self._open_folder)

        subtitle_row = QHBoxLayout()
        subtitle_row.setContentsMargins(0, 0, 0, 0)
        subtitle_row.setSpacing(0)
        subtitle_row.addWidget(self._subtitle_prefix, alignment=Qt.AlignmentFlag.AlignTop)
        subtitle_row.addWidget(self._path_link, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)

        self._edit_button = QPushButton("Edit Project")
        self._edit_button.setObjectName("ghostButton")
        self._edit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_button.clicked.connect(self.edit_requested.emit)

        self._export_button = QPushButton("Export")
        self._export_button.setObjectName("ghostButton")
        self._export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_button.setToolTip("Export numbered photos… (Ctrl+E)")
        self._export_button.clicked.connect(self.export_requested.emit)

        self._analyze_button = QPushButton("✨  Analyze Photos")
        self._analyze_button.setObjectName("aiAnalyzeButton")
        self._analyze_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._analyze_button.clicked.connect(self.analyze_requested.emit)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self._edit_button)
        actions.addWidget(self._export_button)
        actions.addWidget(self._analyze_button)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(4)
        text_col.addWidget(self._title)
        text_col.addLayout(subtitle_row)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addLayout(text_col, stretch=1)
        layout.addLayout(actions)

    def set_project(self, config: ProjectConfig | None) -> None:
        if config is None:
            self._title.setText("No project")
            self._subtitle_prefix.setText("")
            self._path_link.setText("")
            self._path_link.setToolTip("")
            self._folder_path = None
            self._edit_button.setEnabled(False)
            self._export_button.setEnabled(False)
            self._analyze_button.setEnabled(False)
            return
        self._title.setText(config.name)
        created = _format_created(config.created_at)
        refs = len(config.reference_photos)
        location = str(config.input_folder)
        self._folder_path = Path(config.input_folder)
        self._subtitle_prefix.setText(
            f"Created: {created}  ·  Reference photos: {refs}  ·  "
        )
        href = QUrl.fromLocalFile(location).toString()
        self._path_link.setText(
            f'<a href="{href}" style="color:#2F6BFF; text-decoration:underline;">'
            f"{_escape_html(location)}</a>"
        )
        self._path_link.setToolTip(f"Open folder:\n{location}")
        self._edit_button.setEnabled(True)
        self._export_button.setEnabled(True)
        self._analyze_button.setEnabled(True)

    def set_actions_enabled(self, enabled: bool) -> None:
        self._edit_button.setEnabled(enabled)
        self._export_button.setEnabled(enabled)
        self._analyze_button.setEnabled(enabled)

    def _open_folder(self, _link: str) -> None:
        if self._folder_path is None:
            return
        try:
            open_in_file_manager(self._folder_path)
        except FileNotFoundError:
            self._path_link.setToolTip(f"Folder not found:\n{self._folder_path}")


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_created(value: datetime | None) -> str:
    if value is None:
        return "—"
    try:
        return value.strftime("%b %d, %Y")
    except Exception:  # noqa: BLE001
        return str(value)
