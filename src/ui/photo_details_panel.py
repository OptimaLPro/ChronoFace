"""Side panel for inspecting and manually correcting one photo."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QUndoStack
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.commands import FaceReassignCommand, PhotoSnapshotCommand, copy_photo
from src.database.face_repository import FaceRepository
from src.database.photo_repository import PhotoRepository
from src.domain.models import LifeStage, PhotoRecord, ReviewStatus
from src.export.file_exporter import effective_age_for_name
from src.services.identity_correction import IdentityCorrectionService
from src.sorting.grouping import age_group_label
from src.sorting.scoring import apply_sort_decision, decide_sort_for_record
from src.ui.face_reassignment_bar import FaceReassignmentBar
from src.ui.photo_lightbox import open_photo_lightbox
from src.ui.reference_selector import LIFE_STAGE_LABELS
from src.ui.thumbnail_loader import load_thumbnail_pixmap


class _ClickablePreview(QLabel):
    """Preview label that emits when the user clicks an available photo."""

    clicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._clickable = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_clickable(self, enabled: bool) -> None:
        self._clickable = enabled
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if enabled
            else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip("Click to view larger" if enabled else "")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._clickable
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class PhotoDetailsPanel(QWidget):
    """Show analysis details and apply manual corrections."""

    photo_updated = Signal(object)  # PhotoRecord
    analyze_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._photo: PhotoRecord | None = None
        self._project_id: str | None = None
        self._date_of_birth: Optional[date] = None
        self._correction_service: IdentityCorrectionService | None = None
        self._undo_stack: QUndoStack | None = None

        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._preview = _ClickablePreview("Select a photo")
        self._preview.setMinimumHeight(180)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        self._preview.setStyleSheet(
            "QLabel { background: #222; color: #ddd; border: 1px solid #444; }"
        )
        self._preview.clicked.connect(self._open_preview_lightbox)

        self._face_preview = QLabel("Face crop")
        self._face_preview.setMinimumHeight(120)
        self._face_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._face_preview.setStyleSheet(
            "QLabel { background: #1a1a1a; color: #aaa; border: 1px solid #444; }"
        )

        self._face_bar = FaceReassignmentBar()
        self._face_bar.face_clicked.connect(self._on_face_clicked)

        self._add_reference_check = QCheckBox(
            "Also add corrected face as reference (progressive learning)"
        )
        self._add_reference_check.setChecked(True)

        self._life_stage_combo = QComboBox()
        for stage, label in LIFE_STAGE_LABELS.items():
            self._life_stage_combo.addItem(label, stage)

        self._info = QLabel("")
        self._info.setWordWrap(True)

        self._age_spin = QDoubleSpinBox()
        self._age_spin.setRange(0.0, 120.0)
        self._age_spin.setDecimals(1)
        self._age_spin.setSingleStep(0.5)
        self._age_spin.setEnabled(False)

        apply_age = QPushButton("Set Manual Age")
        apply_age.clicked.connect(self._apply_manual_age)
        clear_age = QPushButton("Clear Manual Age")
        clear_age.clicked.connect(self._clear_manual_age)
        self._analyze_button = QPushButton("Re-analyze Faces")
        self._analyze_button.setToolTip(
            "Re-detect faces and estimate a separate AI age for each face"
        )
        self._analyze_button.clicked.connect(self.analyze_requested.emit)
        self._analyze_button.setEnabled(False)
        approve = QPushButton("Mark Approved")
        approve.clicked.connect(self._mark_approved)
        exclude = QPushButton("Exclude from Export")
        exclude.clicked.connect(self._exclude)
        not_target = QPushButton("Mark Not Target Person")
        not_target.clicked.connect(self._mark_not_target)

        age_row = QHBoxLayout()
        age_row.setSpacing(8)
        age_row.addWidget(self._age_spin, stretch=1)
        age_row.addWidget(apply_age)
        age_row.addWidget(clear_age)

        form = QFormLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        form.addRow("Manual age", age_row)

        reference_row = QHBoxLayout()
        reference_row.setSpacing(8)
        reference_row.addWidget(QLabel("Life stage:"))
        reference_row.addWidget(self._life_stage_combo, stretch=1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.addWidget(self._preview)
        content_layout.addWidget(self._face_preview)
        content_layout.addWidget(self._face_bar)
        content_layout.addWidget(self._add_reference_check)
        content_layout.addLayout(reference_row)
        content_layout.addWidget(self._info)
        content_layout.addWidget(self._analyze_button)
        content_layout.addLayout(form)
        content_layout.addWidget(approve)
        content_layout.addWidget(not_target)
        content_layout.addWidget(exclude)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, stretch=1)

    def set_project_context(
        self,
        project_id: str,
        date_of_birth: Optional[date] = None,
        *,
        undo_stack: QUndoStack | None = None,
    ) -> None:
        self._project_id = project_id
        self._date_of_birth = date_of_birth
        self._undo_stack = undo_stack
        self._correction_service = IdentityCorrectionService(
            project_id,
            date_of_birth=date_of_birth,
        )

    def set_undo_stack(self, undo_stack: QUndoStack | None) -> None:
        self._undo_stack = undo_stack

    def set_photo(self, photo: PhotoRecord | None) -> None:
        self._photo = photo
        if photo is None:
            self._preview.setText("Select a photo")
            self._preview.setPixmap(load_thumbnail_pixmap(None))
            self._preview.set_clickable(False)
            self._face_preview.setText("Face crop")
            self._face_preview.setPixmap(load_thumbnail_pixmap(None))
            self._face_bar.clear()
            self._info.setText("")
            self._age_spin.setEnabled(False)
            self._analyze_button.setEnabled(False)
            return

        self._age_spin.setEnabled(True)
        self._analyze_button.setEnabled(True)
        preview = load_thumbnail_pixmap(
            photo.thumbnail_path or photo.original_path,
            size=320,
        )
        if preview.isNull():
            self._preview.setText(photo.original_path.name)
            self._preview.setPixmap(load_thumbnail_pixmap(None))
            self._preview.set_clickable(photo.original_path.is_file())
        else:
            self._preview.setText("")
            self._preview.setPixmap(preview)
            self._preview.set_clickable(True)

        faces = []
        face_path = None
        selected = None
        if self._project_id and photo.id is not None:
            faces = FaceRepository(self._project_id).list_faces_for_photo(photo.id)
            selected = next(
                (face for face in faces if face.is_selected_target),
                None,
            )
            if selected and selected.face_crop_path:
                face_path = selected.face_crop_path
        face_pix = load_thumbnail_pixmap(face_path, size=160)
        if face_pix.isNull():
            self._face_preview.setText("No face crop")
            self._face_preview.setPixmap(load_thumbnail_pixmap(None))
        else:
            self._face_preview.setText("")
            self._face_preview.setPixmap(face_pix)
        self._face_bar.set_faces(faces)

        age = effective_age_for_name(photo, self._date_of_birth)
        if photo.manual_age is not None:
            self._age_spin.setValue(photo.manual_age)
        elif age is not None:
            self._age_spin.setValue(age)
        else:
            self._age_spin.setValue(0.0)

        capture = (
            photo.capture_date.strftime("%Y-%m-%d %H:%M")
            if photo.capture_date
            else "none"
        )
        identity = (
            f"{photo.identity_score:.3f}"
            if photo.identity_score is not None
            else "n/a"
        )
        selected_face_age = (
            f"{selected.estimated_age:.1f}"
            if selected is not None and selected.estimated_age is not None
            else "n/a"
        )
        face_ages = ", ".join(
            (
                f"#{index}:{face.estimated_age:.0f}y"
                if face.estimated_age is not None
                else f"#{index}:?"
            )
            for index, face in enumerate(faces, start=1)
        ) or "none"
        self._info.setText(
            f"File: {photo.original_path.name}\n"
            f"Status: {photo.review_status.value}\n"
            f"Target found: {photo.target_found}\n"
            f"Identity: {identity}\n"
            f"Capture date: {capture} ({photo.date_reliability.value})\n"
            f"Age from DOB: "
            f"{photo.age_from_dob if photo.age_from_dob is not None else 'n/a'}\n"
            f"Selected face AI age: {selected_face_age}\n"
            f"All face ages: {face_ages}\n"
            f"Photo AI age: "
            f"{photo.estimated_age if photo.estimated_age is not None else 'n/a'}\n"
            f"Manual age: "
            f"{photo.manual_age if photo.manual_age is not None else 'n/a'}\n"
            f"Effective age: {age if age is not None else 'n/a'} "
            f"({age_group_label(age)})\n"
            f"Sort score: "
            f"{photo.sort_score if photo.sort_score is not None else 'n/a'}"
        )

    def _open_preview_lightbox(self) -> None:
        if self._photo is None:
            return
        path: Path | None = None
        if self._photo.original_path.is_file():
            path = self._photo.original_path
        elif self._photo.thumbnail_path and Path(self._photo.thumbnail_path).is_file():
            path = Path(self._photo.thumbnail_path)
        open_photo_lightbox(self.window(), path)

    def _on_photo_applied(self, photo: PhotoRecord) -> None:
        self._photo = photo
        self.photo_updated.emit(photo)
        self.set_photo(photo)

    def _push_photo_mutation(self, text: str, mutate) -> None:
        if self._photo is None or not self._project_id:
            return
        before = copy_photo(self._photo)
        after = copy_photo(self._photo)
        mutate(after)
        decision = decide_sort_for_record(
            after,
            date_of_birth=self._date_of_birth,
        )
        apply_sort_decision(
            after, decision, date_of_birth=self._date_of_birth
        )
        if self._undo_stack is not None:
            self._undo_stack.push(
                PhotoSnapshotCommand(
                    self._project_id,
                    before,
                    after,
                    text,
                    on_applied=self._on_photo_applied,
                )
            )
            return
        saved = PhotoRepository(self._project_id).upsert(after)
        self._on_photo_applied(saved)

    def _on_face_clicked(self, face_id: int) -> None:
        if (
            self._photo is None
            or self._correction_service is None
            or not self._project_id
        ):
            return
        stage = self._life_stage_combo.currentData()
        if not isinstance(stage, LifeStage):
            stage = LifeStage.UNKNOWN
        if self._undo_stack is not None:
            try:
                self._undo_stack.push(
                    FaceReassignCommand(
                        self._project_id,
                        self._photo,
                        face_id,
                        also_add_as_reference=self._add_reference_check.isChecked(),
                        reference_life_stage=stage,
                        correction_service=self._correction_service,
                        on_applied=self._on_photo_applied,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Reassignment Failed", str(exc))
            return
        try:
            result = self._correction_service.reassign_target_face(
                self._photo,
                face_id,
                also_add_as_reference=self._add_reference_check.isChecked(),
                reference_life_stage=stage,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Reassignment Failed", str(exc))
            return
        self._on_photo_applied(result.photo)

    def _apply_manual_age(self) -> None:
        if self._photo is None:
            return

        def mutate(photo: PhotoRecord) -> None:
            photo.manual_age = float(self._age_spin.value())
            photo.review_status = ReviewStatus.MANUALLY_CORRECTED

        self._push_photo_mutation("Set manual age", mutate)

    def _clear_manual_age(self) -> None:
        if self._photo is None:
            return

        def mutate(photo: PhotoRecord) -> None:
            photo.manual_age = None
            if photo.review_status == ReviewStatus.MANUALLY_CORRECTED:
                photo.review_status = (
                    ReviewStatus.NEEDS_REVIEW
                    if photo.target_found
                    else ReviewStatus.PENDING
                )

        self._push_photo_mutation("Clear manual age", mutate)

    def _mark_approved(self) -> None:
        if self._photo is None:
            return

        def mutate(photo: PhotoRecord) -> None:
            photo.review_status = ReviewStatus.APPROVED
            if photo.identity_score:
                photo.target_found = True

        self._push_photo_mutation("Mark approved", mutate)

    def _exclude(self) -> None:
        if self._photo is None:
            return

        def mutate(photo: PhotoRecord) -> None:
            photo.review_status = ReviewStatus.EXCLUDED

        self._push_photo_mutation("Exclude from export", mutate)

    def _mark_not_target(self) -> None:
        if self._photo is None:
            return

        def mutate(photo: PhotoRecord) -> None:
            photo.target_found = False
            photo.review_status = ReviewStatus.TARGET_NOT_FOUND
            photo.manual_age = None

        self._push_photo_mutation("Mark not target", mutate)
