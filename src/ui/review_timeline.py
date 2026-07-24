"""Chronological thumbnail timeline for manual review."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.domain.models import PhotoRecord, ReviewStatus
from src.export.file_exporter import effective_age_for_name
from src.sorting.grouping import age_group_label
from src.ui.thumbnail_loader import load_thumbnail_pixmap


class ReviewFilter(str, Enum):
    ALL = "all"
    NEEDS_REVIEW = "needs_review"
    LOW_CONFIDENCE = "low_confidence"
    HIGH_CONFIDENCE = "high_confidence"
    NO_FACE = "no_face"
    NOT_FOUND = "not_found"
    MANUAL = "manual"
    EXCLUDED = "excluded"


FILTER_LABELS = {
    ReviewFilter.ALL: "All photos",
    ReviewFilter.NEEDS_REVIEW: "Needs review / matched",
    ReviewFilter.LOW_CONFIDENCE: "Low confidence",
    ReviewFilter.HIGH_CONFIDENCE: "High confidence matches",
    ReviewFilter.NO_FACE: "No face",
    ReviewFilter.NOT_FOUND: "Target not found",
    ReviewFilter.MANUAL: "Manually corrected",
    ReviewFilter.EXCLUDED: "Excluded",
}


def _status_color(photo: PhotoRecord) -> QColor:
    if photo.review_status == ReviewStatus.MANUALLY_CORRECTED:
        return QColor("#2e7d32")
    if photo.review_status == ReviewStatus.EXCLUDED:
        return QColor("#616161")
    if photo.review_status == ReviewStatus.NO_FACE:
        return QColor("#6a1b9a")
    if photo.review_status == ReviewStatus.TARGET_NOT_FOUND:
        return QColor("#c62828")
    if photo.review_status == ReviewStatus.LOW_CONFIDENCE:
        return QColor("#ef6c00")
    if photo.target_found and (photo.identity_score or 0) >= 0.5:
        return QColor("#1565c0")
    if photo.target_found:
        return QColor("#00838f")
    return QColor("#455a64")


def _matches_filter(photo: PhotoRecord, review_filter: ReviewFilter) -> bool:
    if review_filter == ReviewFilter.ALL:
        return True
    if review_filter == ReviewFilter.NEEDS_REVIEW:
        return (
            photo.review_status
            in {
                ReviewStatus.NEEDS_REVIEW,
                ReviewStatus.PENDING,
            }
            or photo.target_found
        )
    if review_filter == ReviewFilter.LOW_CONFIDENCE:
        return photo.review_status == ReviewStatus.LOW_CONFIDENCE
    if review_filter == ReviewFilter.HIGH_CONFIDENCE:
        return bool(photo.target_found and (photo.identity_score or 0) >= 0.55)
    if review_filter == ReviewFilter.NO_FACE:
        return photo.review_status == ReviewStatus.NO_FACE
    if review_filter == ReviewFilter.NOT_FOUND:
        return photo.review_status == ReviewStatus.TARGET_NOT_FOUND
    if review_filter == ReviewFilter.MANUAL:
        return photo.review_status == ReviewStatus.MANUALLY_CORRECTED
    if review_filter == ReviewFilter.EXCLUDED:
        return photo.review_status == ReviewStatus.EXCLUDED
    return True


class ReviewTimeline(QWidget):
    """Icon timeline of thumbnails with drag-and-drop reordering."""

    selection_changed = Signal(object)  # PhotoRecord | None
    order_changed = Signal(list)  # list[PhotoRecord] in new visual order

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._photos: list[PhotoRecord] = []
        self._filter = ReviewFilter.ALL
        self._date_of_birth: Optional[date] = None
        self.setMinimumWidth(360)

        self._filter_combo = QComboBox()
        for value, label in FILTER_LABELS.items():
            self._filter_combo.addItem(label, value)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)

        self._count_label = QLabel("0 photos")

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(132, 132))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Snap)
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setSpacing(8)
        self._list.setWordWrap(True)
        self._list.itemSelectionChanged.connect(self._emit_selection)
        self._list.model().rowsMoved.connect(self._on_rows_moved)

        header = QHBoxLayout()
        header.addWidget(QLabel("Filter:"))
        header.addWidget(self._filter_combo, stretch=1)
        header.addWidget(self._count_label)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._list, stretch=1)

    def set_date_of_birth(self, date_of_birth: Optional[date]) -> None:
        self._date_of_birth = date_of_birth

    def set_photos(self, photos: list[PhotoRecord]) -> None:
        self._photos = list(photos)
        self._rebuild()

    def photos_in_visual_order(self) -> list[PhotoRecord]:
        ordered: list[PhotoRecord] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            photo = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(photo, PhotoRecord):
                ordered.append(photo)
        return ordered

    def selected_photos(self) -> list[PhotoRecord]:
        photos: list[PhotoRecord] = []
        for item in self._list.selectedItems():
            photo = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(photo, PhotoRecord):
                photos.append(photo)
        return photos

    def refresh_item(self, photo: PhotoRecord) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            current = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(current, PhotoRecord) and current.id == photo.id:
                self._populate_item(item, photo)
                return

    def _on_filter_changed(self) -> None:
        value = self._filter_combo.currentData()
        if isinstance(value, ReviewFilter):
            self._filter = value
        self._rebuild()

    def _rebuild(self) -> None:
        selected_id = None
        selected = self.selected_photos()
        if selected:
            selected_id = selected[0].id

        self._list.blockSignals(True)
        self._list.clear()
        visible = [
            photo for photo in self._photos if _matches_filter(photo, self._filter)
        ]
        for photo in visible:
            item = QListWidgetItem()
            self._populate_item(item, photo)
            self._list.addItem(item)
            if photo.id is not None and photo.id == selected_id:
                item.setSelected(True)
        self._list.blockSignals(False)
        self._count_label.setText(f"{len(visible)} shown / {len(self._photos)} total")
        self._emit_selection()

    def _populate_item(self, item: QListWidgetItem, photo: PhotoRecord) -> None:
        thumb_source = photo.thumbnail_path or photo.original_path
        pixmap = load_thumbnail_pixmap(thumb_source, size=128)
        if not pixmap.isNull():
            item.setIcon(pixmap)

        age = effective_age_for_name(photo, self._date_of_birth)
        age_text = f"{age:.1f}y" if age is not None else "?"
        group = age_group_label(age)
        name = photo.original_path.name
        if len(name) > 28:
            name = name[:25] + "…"
        item.setText(f"{age_text}\n{group}\n{name}")
        item.setData(Qt.ItemDataRole.UserRole, photo)
        item.setToolTip(str(photo.original_path))
        item.setBackground(QBrush(_status_color(photo)))
        item.setForeground(QBrush(QColor("white")))
        item.setSizeHint(QSize(150, 180))

    def _emit_selection(self) -> None:
        selected = self.selected_photos()
        self.selection_changed.emit(selected[0] if selected else None)

    def _on_rows_moved(self, *_args) -> None:
        visual = self.photos_in_visual_order()
        if self._filter == ReviewFilter.ALL:
            self._photos = visual
        self.order_changed.emit(visual)
