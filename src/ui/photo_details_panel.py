"""Side panel for inspecting and manually correcting one photo."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QUndoStack
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.commands import FaceReassignCommand, PhotoSnapshotCommand, copy_photo
from src.database.face_repository import FaceRepository
from src.database.photo_repository import PhotoRepository
from src.domain.match_status import is_no_match_photo
from src.domain.models import DateReliability, PhotoRecord, ReviewStatus
from src.export.file_exporter import effective_age_for_name
from src.services.identity_correction import IdentityCorrectionService
from src.sorting.scoring import apply_sort_decision, decide_sort_for_record
from src.ui.face_reassignment_bar import FaceReassignmentBar
from src.ui.photo_lightbox import open_photo_lightbox
from src.ui.thumbnail_loader import load_thumbnail_pixmap
from src.ui.message_dialog import MessageDialog


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
    """Inspector: preview, match score, editable fields, detected faces."""

    photo_updated = Signal(object)  # PhotoRecord
    analyze_requested = Signal()
    remove_requested = Signal(object)  # PhotoRecord

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._photo: PhotoRecord | None = None
        self._project_id: str | None = None
        self._date_of_birth: Optional[date] = None
        self._correction_service: IdentityCorrectionService | None = None
        self._undo_stack: QUndoStack | None = None
        self._suppress_autosave = False

        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        preview_wrap = QFrame()
        preview_wrap.setObjectName("previewWrap")
        preview_wrap.setStyleSheet(
            "QFrame#previewWrap {"
            "  background: #111827; border-radius: 12px;"
            "}"
        )
        self._preview = _ClickablePreview("Select a photo")
        self._preview.setMinimumHeight(200)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        self._preview.setStyleSheet(
            "QLabel { background: transparent; color: #D1D5DB; border: none; }"
        )
        self._preview.clicked.connect(self._open_preview_lightbox)

        self._badge = QLabel("")
        self._badge.setParent(preview_wrap)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.hide()
        self._badge.setStyleSheet(
            "QLabel {"
            "  background: #16A34A; color: white; font-weight: 700;"
            "  font-size: 11px; border-radius: 6px; padding: 4px 8px;"
            "}"
        )
        self._badge.move(10, 10)
        self._badge.raise_()

        preview_layout = QVBoxLayout(preview_wrap)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self._preview)
        self._preview_wrap = preview_wrap

        self._filename = QLabel("")
        self._filename.setStyleSheet("font-weight: 700; font-size: 13px;")
        self._filename.setWordWrap(True)

        self._age_label = QLabel("")
        self._age_label.setObjectName("mutedLabel")
        self._date_label = QLabel("")
        self._date_label.setObjectName("mutedLabel")

        match_header = QHBoxLayout()
        match_title = QLabel("Match score")
        match_title.setObjectName("mutedLabel")
        self._match_value = QLabel("—")
        self._match_value.setStyleSheet("font-weight: 700; color: #16A34A;")
        match_header.addWidget(match_title)
        match_header.addStretch(1)
        match_header.addWidget(self._match_value)

        self._match_bar = QProgressBar()
        self._match_bar.setObjectName("successBar")
        self._match_bar.setRange(0, 100)
        self._match_bar.setValue(0)
        self._match_bar.setTextVisible(False)
        self._match_bar.setFixedHeight(8)

        self._age_spin = QDoubleSpinBox()
        self._age_spin.setRange(0.0, 120.0)
        self._age_spin.setDecimals(1)
        self._age_spin.setSingleStep(0.5)
        self._age_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._age_spin.setEnabled(False)
        self._age_spin.editingFinished.connect(self._autosave_fields)

        self._status_combo = QComboBox()
        self._status_combo.addItem("Target person", "target")
        self._status_combo.addItem("Needs review", "needs_review")
        self._status_combo.addItem("Approved", "approved")
        self._status_combo.addItem("Not target", "not_target")
        self._status_combo.addItem("Removed", "excluded")
        self._status_combo.setEnabled(False)
        self._status_combo.currentIndexChanged.connect(self._autosave_fields)

        self._date_display = QLabel("—")
        self._date_display.setObjectName("mutedLabel")

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow("Age (years)", self._age_spin)
        form.addRow("Date", self._date_display)
        form.addRow("Status", self._status_combo)

        self._approve_button = QPushButton("Approve")
        self._approve_button.setObjectName("primaryButton")
        self._approve_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._approve_button.setEnabled(False)
        self._approve_button.setToolTip(
            "Confirm this photo shows the target and move it out of Needs review"
        )
        self._approve_button.clicked.connect(self._approve_photo)

        self._remove_button = QPushButton("Remove Photo")
        self._remove_button.setObjectName("dangerButton")
        self._remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_button.setEnabled(False)
        self._remove_button.setToolTip(
            "Remove this photo from the project (file stays on disk)"
        )
        self._remove_button.clicked.connect(self._request_remove)

        self._analyze_button = QPushButton("Re-analyze Faces")
        self._analyze_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._analyze_button.setToolTip(
            "Re-detect faces and estimate a separate AI age for each face"
        )
        self._analyze_button.clicked.connect(self.analyze_requested.emit)
        self._analyze_button.setEnabled(False)

        self._face_bar = FaceReassignmentBar()
        self._face_bar.face_clicked.connect(self._on_face_clicked)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(14, 4, 14, 8)
        details_layout.setSpacing(12)
        details_layout.addWidget(self._filename)
        details_layout.addWidget(self._age_label)
        details_layout.addWidget(self._date_label)
        details_layout.addLayout(match_header)
        details_layout.addWidget(self._match_bar)
        details_layout.addSpacing(4)
        details_layout.addLayout(form)
        details_layout.addWidget(self._approve_button)
        details_layout.addWidget(self._remove_button)
        details_layout.addWidget(self._analyze_button)
        details_layout.addWidget(self._face_bar)
        details_layout.addStretch(1)

        content = QWidget()
        content.setObjectName("photoDetailsContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(8)
        content_layout.addWidget(preview_wrap)
        content_layout.addWidget(details)

        scroll = QScrollArea()
        scroll.setObjectName("photoDetailsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setStyleSheet(
            "QScrollArea#photoDetailsScroll,"
            "QScrollArea#photoDetailsScroll > QWidget {"
            "  background: transparent; border: none;"
            "}"
            "QWidget#photoDetailsContent { background: transparent; }"
        )

        self.setObjectName("photoDetailsPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#photoDetailsPanel { background: transparent; }"
        )

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
        self._suppress_autosave = True
        try:
            if photo is None:
                self._preview.setText("Select a photo")
                self._preview.setPixmap(load_thumbnail_pixmap(None))
                self._preview.set_clickable(False)
                self._badge.hide()
                self._filename.setText("")
                self._age_label.setText("")
                self._date_label.setText("")
                self._match_value.setText("—")
                self._match_bar.setValue(0)
                self._date_display.setText("—")
                self._face_bar.clear()
                self._age_spin.setEnabled(False)
                self._status_combo.setEnabled(False)
                self._approve_button.setEnabled(False)
                self._remove_button.setEnabled(False)
                self._analyze_button.setEnabled(False)
                return

            self._age_spin.setEnabled(True)
            self._status_combo.setEnabled(True)
            self._approve_button.setEnabled(
                photo.review_status != ReviewStatus.APPROVED
            )
            self._remove_button.setEnabled(True)
            self._analyze_button.setEnabled(True)

            preview = load_thumbnail_pixmap(
                photo.thumbnail_path or photo.original_path,
                size=360,
            )
            if preview.isNull():
                self._preview.setText(photo.original_path.name)
                self._preview.setPixmap(load_thumbnail_pixmap(None))
                self._preview.set_clickable(photo.original_path.is_file())
            else:
                self._preview.setText("")
                self._preview.setPixmap(preview)
                self._preview.set_clickable(True)

            score = photo.identity_score
            has_exif = photo.date_reliability == DateReliability.RELIABLE_EXIF
            no_match = is_no_match_photo(photo)
            # High/Low match feed Target found; No match feeds Not found.
            matched = (
                not no_match
                and photo.review_status != ReviewStatus.EXCLUDED
                and (
                    photo.target_found
                    or photo.review_status == ReviewStatus.LOW_CONFIDENCE
                )
            )
            # EXIF date makes age trustworthy — treat as high match even if face score is low.
            is_high_match = matched and (
                (score is not None and score >= 0.55) or has_exif
            )
            is_low_match = matched and not is_high_match and (
                photo.review_status == ReviewStatus.LOW_CONFIDENCE
                or (score is not None and score < 0.55)
                or photo.target_found
            )
            if is_high_match:
                self._badge.setText("High match")
                self._badge.setStyleSheet(
                    "QLabel {"
                    "  background: #16A34A; color: white; font-weight: 700;"
                    "  font-size: 11px; border-radius: 6px; padding: 4px 8px;"
                    "}"
                )
                self._show_badge()
            elif is_low_match:
                self._badge.setText("Low match")
                self._badge.setStyleSheet(
                    "QLabel {"
                    "  background: #D97706; color: white; font-weight: 700;"
                    "  font-size: 11px; border-radius: 6px; padding: 4px 8px;"
                    "}"
                )
                self._show_badge()
            elif no_match:
                self._badge.setText("No match")
                self._badge.setStyleSheet(
                    "QLabel {"
                    "  background: #DC2626; color: white; font-weight: 700;"
                    "  font-size: 11px; border-radius: 6px; padding: 4px 8px;"
                    "}"
                )
                self._show_badge()
            else:
                self._badge.hide()

            faces = []
            if self._project_id and photo.id is not None:
                faces = FaceRepository(self._project_id).list_faces_for_photo(photo.id)
            self._face_bar.set_faces(faces)

            age = effective_age_for_name(photo, self._date_of_birth)
            self._age_spin.blockSignals(True)
            if photo.manual_age is not None:
                self._age_spin.setValue(photo.manual_age)
            elif age is not None:
                self._age_spin.setValue(age)
            else:
                self._age_spin.setValue(0.0)
            self._age_spin.blockSignals(False)

            conf = photo.age_confidence
            age_text = (
                f"{age:.1f} years old"
                if age is not None
                else "Age unknown"
            )
            if conf is not None and age is not None:
                age_text += f" (± {conf:.1f})"
            self._age_label.setText(age_text)

            if photo.capture_date:
                date_text = photo.capture_date.strftime("%Y-%m-%d")
                if photo.date_reliability == DateReliability.RELIABLE_EXIF:
                    date_text += " (EXIF)"
                elif photo.date_reliability == DateReliability.WEAK_FILESYSTEM:
                    date_text += " (filesystem)"
            else:
                date_text = "No date"
            self._date_label.setText(date_text)
            self._date_display.setText(date_text)

            self._filename.setText(photo.original_path.name)
            if score is not None:
                self._match_value.setText(f"{score:.2f}")
                self._match_bar.setValue(int(max(0.0, min(1.0, score)) * 100))
                trusted = score >= 0.55 or has_exif
                color = "#16A34A" if trusted else "#D97706"
                self._match_value.setStyleSheet(f"font-weight: 700; color: {color};")
            else:
                self._match_value.setText("—")
                self._match_bar.setValue(0)

            self._sync_status_combo(photo)
        finally:
            self._suppress_autosave = False

    def _show_badge(self) -> None:
        self._badge.adjustSize()
        self._badge.move(10, 10)
        self._badge.show()
        self._badge.raise_()

    def _sync_status_combo(self, photo: PhotoRecord) -> None:
        index = self._status_combo.findData(self._status_key_for_photo(photo))
        if index >= 0:
            self._status_combo.blockSignals(True)
            self._status_combo.setCurrentIndex(index)
            self._status_combo.blockSignals(False)

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
        # Refresh inspector first; listeners (timeline) may then advance
        # selection after an exclude and overwrite via selection_changed.
        self.set_photo(photo)
        self.photo_updated.emit(photo)

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

    def _fields_match_photo(self) -> bool:
        """True when Age/Status widgets already match the loaded photo."""
        if self._photo is None:
            return True
        status_key = self._status_combo.currentData()
        age_value = float(self._age_spin.value())
        expected_age = self._photo.manual_age
        if expected_age is None:
            expected_age = effective_age_for_name(self._photo, self._date_of_birth)
        if expected_age is None:
            age_matches = age_value == 0.0
        else:
            age_matches = abs(age_value - float(expected_age)) < 0.05

        # Mirror _sync_status_combo so we don't rewrite identical status.
        sync_key = self._status_key_for_photo(self._photo)
        return age_matches and status_key == sync_key

    def _status_key_for_photo(self, photo: PhotoRecord) -> str:
        has_exif = photo.date_reliability == DateReliability.RELIABLE_EXIF
        score = photo.identity_score
        if photo.review_status == ReviewStatus.EXCLUDED:
            return "excluded"
        if photo.review_status == ReviewStatus.APPROVED:
            return "approved"
        if is_no_match_photo(photo):
            return "not_target"
        if photo.target_found and (
            (score is not None and score >= 0.55) or has_exif
        ):
            return "target"
        if photo.review_status in {
            ReviewStatus.NEEDS_REVIEW,
            ReviewStatus.LOW_CONFIDENCE,
            ReviewStatus.PENDING,
        }:
            return "needs_review"
        return "target" if photo.target_found else "needs_review"

    def _apply_status_and_age(
        self,
        photo: PhotoRecord,
        *,
        status_key: str,
        age_value: float,
    ) -> None:
        photo.manual_age = age_value
        if status_key == "excluded":
            photo.review_status = ReviewStatus.EXCLUDED
        elif status_key == "approved":
            photo.review_status = ReviewStatus.APPROVED
            photo.target_found = True
        elif status_key == "not_target":
            photo.target_found = False
            photo.review_status = ReviewStatus.TARGET_NOT_FOUND
        elif status_key == "needs_review":
            photo.review_status = ReviewStatus.NEEDS_REVIEW
        else:
            photo.target_found = True
            photo.review_status = ReviewStatus.MANUALLY_CORRECTED

    def _autosave_fields(self) -> None:
        """Persist Age/Status as soon as the user edits them."""
        if self._suppress_autosave or self._photo is None:
            return
        if self._fields_match_photo():
            return
        status_key = self._status_combo.currentData()
        age_value = float(self._age_spin.value())
        # Only rewrite review_status when the user actually changed Status.
        # Age-only edits must not collapse LOW_CONFIDENCE → NEEDS_REVIEW.
        status_changed = status_key != self._status_key_for_photo(self._photo)

        def mutate(photo: PhotoRecord) -> None:
            if status_changed:
                self._apply_status_and_age(
                    photo, status_key=status_key, age_value=age_value
                )
            else:
                photo.manual_age = age_value

        self._push_photo_mutation("Edit photo fields", mutate)

    def _approve_photo(self) -> None:
        """Mark target confirmed and drop the photo out of Needs review."""
        if self._photo is None:
            return
        age_value = float(self._age_spin.value())

        def mutate(photo: PhotoRecord) -> None:
            self._apply_status_and_age(
                photo, status_key="approved", age_value=age_value
            )

        self._push_photo_mutation("Approve photo", mutate)

    def _on_face_clicked(self, face_id: int) -> None:
        if (
            self._photo is None
            or self._correction_service is None
            or not self._project_id
        ):
            return
        if self._undo_stack is not None:
            try:
                self._undo_stack.push(
                    FaceReassignCommand(
                        self._project_id,
                        self._photo,
                        face_id,
                        also_add_as_reference=True,
                        correction_service=self._correction_service,
                        on_applied=self._on_photo_applied,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                MessageDialog.critical(self, "Reassignment Failed", str(exc))
            return
        try:
            result = self._correction_service.reassign_target_face(
                self._photo,
                face_id,
                also_add_as_reference=True,
            )
        except Exception as exc:  # noqa: BLE001
            MessageDialog.critical(self, "Reassignment Failed", str(exc))
            return
        self._on_photo_applied(result.photo)

    def _request_remove(self) -> None:
        """Ask parent to confirm, same path as timeline context menu."""
        if self._photo is None:
            return
        self.remove_requested.emit(self._photo)

    def remove_current_photo(self) -> None:
        """Soft-remove current photo from project (undoable when stack set)."""
        if self._photo is None:
            return

        def mutate(photo: PhotoRecord) -> None:
            photo.review_status = ReviewStatus.EXCLUDED

        self._push_photo_mutation("Remove from project", mutate)
