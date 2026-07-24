"""Widget for selecting and tagging reference photos of the target person."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.models import LifeStage, ReferencePhoto
from src.utils.image_utils import is_supported_image

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

LIFE_STAGE_LABELS = {
    LifeStage.UNKNOWN: "Unspecified",
    LifeStage.BABY: "Baby",
    LifeStage.CHILDHOOD: "Childhood",
    LifeStage.TEENAGE: "Teenage years",
    LifeStage.ADULTHOOD: "Adulthood",
}


def format_reference_label(index: int, reference: ReferencePhoto) -> str:
    """List label: show life stage only when the user set one."""
    label = f"{index + 1}. {reference.file_path.name}"
    if reference.life_stage != LifeStage.UNKNOWN:
        stage = LIFE_STAGE_LABELS.get(
            reference.life_stage, reference.life_stage.value
        )
        label = f"{label} [{stage}]"
    return label


class ReferenceSelector(QWidget):
    """Select multiple reference images and assign optional life-stage groups."""

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

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.currentRowChanged.connect(self._on_selection_changed)

        self._stage_combo = QComboBox()
        for stage, label in LIFE_STAGE_LABELS.items():
            self._stage_combo.addItem(label, stage)
        self._stage_combo.currentIndexChanged.connect(self._on_stage_changed)
        self._stage_combo.setEnabled(False)

        self._preview = QLabel("No reference selected")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(160)
        self._preview.setStyleSheet(
            "QLabel { background: #f3f3f3; border: 1px solid #ccc; color: #555; }"
        )

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

        stage_row = QHBoxLayout()
        stage_row.addWidget(QLabel("Life stage for selected:"))
        stage_row.addWidget(self._stage_combo, stretch=1)

        hint = QLabel(
            "Add 3–10 photos of the same person across ages when possible "
            "(baby, child, teen, adult). Different angles and lighting help."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555;")

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(button_row)
        layout.addWidget(self._list, stretch=2)
        layout.addLayout(stage_row)
        layout.addWidget(self._preview, stretch=1)

    def references(self) -> list[ReferencePhoto]:
        """Return a copy of the current reference list."""
        return [
            ReferencePhoto(
                file_path=ref.file_path,
                life_stage=ref.life_stage,
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
                life_stage=ref.life_stage,
                sort_order=ref.sort_order,
                id=ref.id,
            )
            for ref in references
        ]
        self._refresh_list()
        self.references_changed.emit()

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
            QMessageBox.warning(
                self,
                "Unsupported Files",
                "These files were skipped (unsupported type):\n"
                + "\n".join(skipped[:10]),
            )

        if added:
            self._refresh_list()
            self.references_changed.emit()

    def _remove_selected(self) -> None:
        rows = sorted(
            {index.row() for index in self._list.selectedIndexes()},
            reverse=True,
        )
        if not rows:
            return
        for row in rows:
            if 0 <= row < len(self._references):
                del self._references[row]
        self._refresh_list()
        self.references_changed.emit()

    def _move_selected(self, delta: int) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        target = row + delta
        if target < 0 or target >= len(self._references):
            return
        self._references[row], self._references[target] = (
            self._references[target],
            self._references[row],
        )
        self._refresh_list()
        self._list.setCurrentRow(target)
        self.references_changed.emit()

    def _on_selection_changed(self, row: int) -> None:
        self._stage_combo.blockSignals(True)
        if row < 0 or row >= len(self._references):
            self._stage_combo.setEnabled(False)
            self._preview.setText("No reference selected")
            self._preview.setPixmap(QPixmap())
            self._stage_combo.blockSignals(False)
            return

        reference = self._references[row]
        self._stage_combo.setEnabled(True)
        stage_index = self._stage_combo.findData(reference.life_stage)
        self._stage_combo.setCurrentIndex(max(stage_index, 0))
        self._stage_combo.blockSignals(False)
        self._show_preview(reference.file_path)

    def _on_stage_changed(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._references):
            return
        stage = self._stage_combo.currentData()
        if isinstance(stage, LifeStage):
            self._references[row].life_stage = stage
            self._refresh_list(keep_row=row)
            self.references_changed.emit()

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

    def _refresh_list(self, keep_row: int | None = None) -> None:
        current = self._list.currentRow() if keep_row is None else keep_row
        self._list.clear()
        for index, reference in enumerate(self._references):
            reference.sort_order = index
            item = QListWidgetItem(format_reference_label(index, reference))
            item.setToolTip(str(reference.file_path))
            self._list.addItem(item)

        if self._references:
            self._list.setCurrentRow(min(max(current, 0), len(self._references) - 1))
        else:
            self._on_selection_changed(-1)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        row = self._list.currentRow()
        if 0 <= row < len(self._references):
            self._show_preview(self._references[row].file_path)
