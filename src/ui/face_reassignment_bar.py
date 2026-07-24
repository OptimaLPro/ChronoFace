"""Horizontal strip of detected face crops for manual target reassignment."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.database.face_repository import FaceRecord
from src.ui.thumbnail_loader import load_thumbnail_pixmap


class FaceReassignmentBar(QWidget):
    """Show all detected faces for a photo; click one to pick the target."""

    face_clicked = Signal(int)  # face id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._title = QLabel("Detected faces")
        self._title.setStyleSheet("font-weight: 600;")

        self._hint = QLabel(
            "Click the correct face if the wrong person was picked."
        )
        self._hint.setStyleSheet("color: #888;")
        self._hint.setWordWrap(True)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(96, 96))
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setFlow(QListWidget.Flow.LeftToRight)
        self._list.setWrapping(True)
        self._list.setSpacing(6)
        self._list.setFixedHeight(168)
        self._list.itemClicked.connect(self._on_item_clicked)

        header = QHBoxLayout()
        header.addWidget(self._title)
        header.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self._hint)
        layout.addWidget(self._list)

    def set_faces(self, faces: list[FaceRecord]) -> None:
        self._list.clear()
        if not faces:
            self._hint.setText("No faces detected for this photo.")
            return
        self._hint.setText(
            "Each face has its own AI age. Click the correct person to use "
            f"their age for this photo. ({len(faces)} face(s))"
        )
        for index, face in enumerate(faces, start=1):
            item = QListWidgetItem()
            pix = load_thumbnail_pixmap(face.face_crop_path, size=96)
            if not pix.isNull():
                item.setIcon(pix)
            score = (
                f"{face.identity_score:.2f}"
                if face.identity_score is not None
                else "?"
            )
            if face.estimated_age is not None:
                age_text = f"{face.estimated_age:.0f}y"
            else:
                age_text = "?y"
            marker = " ★" if face.is_selected_target else ""
            item.setText(f"#{index}{marker}\n{age_text}\n{score}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setData(Qt.ItemDataRole.UserRole, face.id)
            item.setSizeHint(QSize(112, 156))
            quality = (
                f"{face.quality_score:.2f}"
                if face.quality_score is not None
                else "n/a"
            )
            age_tip = (
                f"{face.estimated_age:.1f} years"
                if face.estimated_age is not None
                else "not estimated yet — re-analyze this photo"
            )
            item.setToolTip(
                f"Face #{index}\n"
                f"AI age: {age_tip}\n"
                f"Identity score: {score}\n"
                f"Quality: {quality}"
            )
            self._list.addItem(item)
            if face.is_selected_target:
                item.setSelected(True)

    def clear(self) -> None:
        self._list.clear()
        self._hint.setText("No photo selected.")

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        face_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(face_id, int):
            self.face_clicked.emit(face_id)
