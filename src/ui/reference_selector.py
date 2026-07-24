"""Widget for selecting reference photos of the target person."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.domain.models import LifeStage, ReferencePhoto
from src.utils.image_utils import is_supported_image
from src.ui.message_dialog import MessageDialog

_DEFAULT_BUTTON_STYLE = (
    "QPushButton {"
    "  font-weight: 600; padding: 8px 14px;"
    "  background: #2a2f38; color: #ffffff; border: 1px solid #1f242c;"
    "  border-radius: 6px;"
    "}"
    "QPushButton:hover { background: #3a414d; border-color: #2a2f38; }"
    "QPushButton:pressed { background: #1f242c; }"
    "QPushButton:disabled {"
    "  color: #9aa1ab; background: #e8eaee; border-color: #d5d8de;"
    "}"
)

_CANVAS_STYLE = (
    "QFrame#photoCanvas {"
    "  background: #ffffff;"
    "  border: 1px solid #e2e8f0;"
    "  border-radius: 6px;"
    "}"
)

_TABLE_STYLE = (
    "QTableWidget {"
    "  background: transparent; alternate-background-color: #f8fafc;"
    "  border: none; border-radius: 6px;"
    "  gridline-color: #edf0f4;"
    "  selection-background-color: #e8eefc; selection-color: #1e293b;"
    "  font-size: 12px;"
    "}"
    "QTableWidget::item { padding: 4px 8px; }"
    "QHeaderView::section {"
    "  background: #f7f9fc; color: #475569; font-weight: 600;"
    "  border: none; border-bottom: 1px solid #e2e8f0;"
    "  border-right: 1px solid #edf0f4; padding: 6px 8px;"
    "}"
    "QHeaderView::section:first { border-top-left-radius: 6px; }"
    "QHeaderView::section:last {"
    "  border-right: none; border-top-right-radius: 6px;"
    "}"
    "QHeaderView::section:hover { background: #eef2f7; color: #1e293b; }"
)

_HINT_BUBBLE_STYLE = (
    "QLabel {"
    "  background: #eef4ff; border: 1px solid #b7c9f0;"
    "  border-radius: 6px; padding: 10px 12px; color: #1e3a6e;"
    "  font-weight: 600;"
    "}"
)

_PREVIEW_STYLE = (
    "QLabel {"
    "  background: transparent; color: #555;"
    "  border: none; border-radius: 6px;"
    "}"
)

_TABLE_COLUMNS = ("#", "File")


def _wrap_canvas(widget: QWidget) -> QFrame:
    canvas = QFrame()
    canvas.setObjectName("photoCanvas")
    canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    canvas.setStyleSheet(_CANVAS_STYLE)
    layout = QVBoxLayout(canvas)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    layout.addWidget(widget)
    return canvas


class ReferenceSelector(QWidget):
    """Select multiple reference images of the target person."""

    references_changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        button_style: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._references: list[ReferencePhoto] = []
        style = button_style or _DEFAULT_BUTTON_STYLE

        self._table = QTableWidget()
        self._table.setColumnCount(len(_TABLE_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_TABLE_COLUMNS))
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.setFrameShape(QFrame.Shape.NoFrame)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 40)
        # Keep enough viewport height to show at least four reference rows.
        row_height = max(self._table.verticalHeader().defaultSectionSize(), 28)
        header_height = max(self._table.horizontalHeader().sizeHint().height(), 28)
        self._table.setMinimumHeight(header_height + (row_height * 4) + 8)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._preview = QLabel("No reference selected")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(160)
        self._preview.setStyleSheet(_PREVIEW_STYLE)

        add_button = QPushButton("Add Reference Photos…")
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.setStyleSheet(style)
        add_button.clicked.connect(self._add_references)

        remove_button = QPushButton("Remove Selected")
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.setStyleSheet(style)
        remove_button.clicked.connect(self._remove_selected)

        move_up = QPushButton("Move Up")
        move_up.setCursor(Qt.CursorShape.PointingHandCursor)
        move_up.setStyleSheet(style)
        move_up.clicked.connect(lambda: self._move_selected(-1))

        move_down = QPushButton("Move Down")
        move_down.setCursor(Qt.CursorShape.PointingHandCursor)
        move_down.setStyleSheet(style)
        move_down.clicked.connect(lambda: self._move_selected(1))

        button_row = QHBoxLayout()
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addWidget(move_up)
        button_row.addWidget(move_down)
        button_row.addStretch(1)

        hint = QLabel(
            "Add 3–10 photos of the same person across ages when possible "
            "(baby, child, teen, adult). Different angles and lighting help."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_HINT_BUBBLE_STYLE)

        table_canvas = _wrap_canvas(self._table)
        preview_canvas = _wrap_canvas(self._preview)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(hint)
        layout.addLayout(button_row)
        layout.addWidget(table_canvas, stretch=2)
        layout.addWidget(preview_canvas, stretch=1)

    def references(self) -> list[ReferencePhoto]:
        """Return a copy of the current reference list."""
        return [
            ReferencePhoto(
                file_path=ref.file_path,
                life_stage=LifeStage.UNKNOWN,
                sort_order=index,
                id=ref.id,
            )
            for index, ref in enumerate(self._references)
        ]

    def set_references(self, references: list[ReferencePhoto]) -> None:
        """Replace the reference list (e.g. when editing an existing project)."""
        self._references = [
            ReferencePhoto(
                file_path=Path(ref.file_path),
                life_stage=LifeStage.UNKNOWN,
                sort_order=ref.sort_order,
                id=ref.id,
            )
            for ref in references
        ]
        self._refresh_table()
        self.references_changed.emit()

    def _current_row(self) -> int:
        return self._table.currentRow()

    def _selected_rows(self) -> list[int]:
        rows = {index.row() for index in self._table.selectedIndexes()}
        return sorted(rows)

    def _add_references(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Reference Photos",
            "",
            "Images (*.jpg *.jpeg *.png *.webp);;All Files (*)",
        )
        if not paths:
            return

        existing = {str(ref.file_path.resolve()) for ref in self._references}
        added = 0
        skipped: list[str] = []

        for raw in paths:
            path = Path(raw)
            if not is_supported_image(path):
                skipped.append(path.name)
                continue
            resolved = str(path.resolve())
            if resolved in existing:
                continue
            self._references.append(
                ReferencePhoto(
                    file_path=path.resolve(),
                    life_stage=LifeStage.UNKNOWN,
                    sort_order=len(self._references),
                )
            )
            existing.add(resolved)
            added += 1

        if skipped:
            MessageDialog.warning(
                self,
                "Unsupported Files",
                "These files were skipped (unsupported type):\n"
                + "\n".join(skipped[:10]),
            )

        if added:
            self._refresh_table()
            self.references_changed.emit()

    def _remove_selected(self) -> None:
        rows = sorted(self._selected_rows(), reverse=True)
        if not rows:
            return
        for row in rows:
            if 0 <= row < len(self._references):
                del self._references[row]
        self._refresh_table()
        self.references_changed.emit()

    def _move_selected(self, delta: int) -> None:
        row = self._current_row()
        if row < 0:
            return
        target = row + delta
        if target < 0 or target >= len(self._references):
            return
        self._references[row], self._references[target] = (
            self._references[target],
            self._references[row],
        )
        self._refresh_table(keep_row=target)
        self.references_changed.emit()

    def _on_selection_changed(self) -> None:
        row = self._current_row()
        if row < 0 or row >= len(self._references):
            self._preview.setText("No reference selected")
            self._preview.setPixmap(QPixmap())
            return
        self._show_preview(self._references[row].file_path)

    def _show_preview(self, path: Path) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._preview.setText(f"Could not load preview:\n{path.name}")
            self._preview.setPixmap(QPixmap())
            return
        scaled = pixmap.scaled(
            self._preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(scaled)

    def _refresh_table(self, keep_row: int | None = None) -> None:
        current = self._current_row() if keep_row is None else keep_row
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._references))
        for index, reference in enumerate(self._references):
            reference.sort_order = index

            index_item = QTableWidgetItem(str(index + 1))
            index_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            index_item.setToolTip(str(reference.file_path))

            file_item = QTableWidgetItem(reference.file_path.name)
            file_item.setToolTip(str(reference.file_path))

            self._table.setItem(index, 0, index_item)
            self._table.setItem(index, 1, file_item)

        if self._references:
            row = min(max(current, 0), len(self._references) - 1)
            self._table.selectRow(row)
            self._table.setCurrentCell(row, 0)
        else:
            self._on_selection_changed()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        row = self._current_row()
        if 0 <= row < len(self._references):
            self._show_preview(self._references[row].file_path)
