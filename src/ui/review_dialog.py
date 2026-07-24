"""Full-window manual review workspace."""

from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from PySide6.QtCore import QObject, QSettings, QSize, QThread, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from src.database.photo_repository import PhotoRepository
from src.domain.models import PhotoRecord, ReferencePhoto, ReviewStatus
from src.sorting.ranking import rank_photo_records
from src.ui.photo_details_panel import PhotoDetailsPanel
from src.ui.review_timeline import ReviewFilter, ReviewTimeline
from src.workers.face_pipeline import FaceAnalysisPipeline, FacePipelineConfig


class _SinglePhotoWorker(QObject):
    """Re-run face analysis for one or more selected photos."""

    progress = Signal(int, int, str)
    finished = Signal(list)  # list[PhotoRecord]
    error = Signal(str)

    def __init__(
        self,
        *,
        project_id: str,
        reference_photos: Sequence[ReferencePhoto],
        date_of_birth: Optional[date],
        photo_ids: Sequence[int],
    ) -> None:
        super().__init__()
        self._project_id = project_id
        self._reference_photos = list(reference_photos)
        self._date_of_birth = date_of_birth
        self._photo_ids = list(photo_ids)

    def run(self) -> None:
        try:
            pipeline = FaceAnalysisPipeline(
                FacePipelineConfig(
                    project_id=self._project_id,
                    reference_photos=self._reference_photos,
                    date_of_birth=self._date_of_birth,
                    force_reprocess=True,
                )
            )
            updated = pipeline.reanalyze_photos(
                self._photo_ids,
                on_progress=lambda current, total, message: self.progress.emit(
                    current, total, message
                ),
            )
            self.finished.emit(updated)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc).strip() or type(exc).__name__)


class ReviewDialog(QDialog):
    """Review thumbnails, drag to reorder, and apply manual corrections."""

    def __init__(
        self,
        parent=None,
        *,
        project_id: str,
        date_of_birth: Optional[date] = None,
        project_name: str = "Project",
        reference_photos: Sequence[ReferencePhoto] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Review — {project_name}")
        self.setMinimumSize(QSize(900, 600))
        self.resize(1200, 780)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self._project_id = project_id
        self._date_of_birth = date_of_birth
        self._reference_photos = list(reference_photos or [])
        self._repo = PhotoRepository(project_id)
        self._dirty_order = False
        self._settings = QSettings("ChronoFace", "ChronoFace")
        self._worker_thread: QThread | None = None
        self._worker: _SinglePhotoWorker | None = None
        self._progress: QProgressDialog | None = None

        hint = QLabel(
            "Drag thumbnails to fix order (youngest → oldest). "
            "Select a photo to edit age, re-analyze, approve, exclude, "
            "or mark as not the target. "
            "Colors: blue=match, orange=low confidence, red=not found, "
            "purple=no face, green=manual."
        )
        hint.setWordWrap(True)

        self._timeline = ReviewTimeline()
        self._timeline.set_date_of_birth(date_of_birth)
        self._details = PhotoDetailsPanel()
        self._details.set_project_context(project_id, date_of_birth)

        self._timeline.selection_changed.connect(self._details.set_photo)
        self._timeline.order_changed.connect(self._on_order_changed)
        self._details.photo_updated.connect(self._on_photo_updated)
        self._details.analyze_requested.connect(self._analyze_selected_photos)

        save_order = QPushButton("Save Current Order")
        save_order.clicked.connect(self._save_order)

        re_rank = QPushButton("Re-rank by Ages")
        re_rank.clicked.connect(self._rerank_by_ages)

        self._analyze_selected = QPushButton("Re-analyze Selected")
        self._analyze_selected.setToolTip(
            "Re-detect faces and estimate a separate AI age for each face "
            "in the selected photo(s)"
        )
        self._analyze_selected.clicked.connect(self._analyze_selected_photos)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._timeline)
        self._splitter.addWidget(self._details)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([720, 400])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self._on_close)

        actions = QHBoxLayout()
        actions.addWidget(save_order)
        actions.addWidget(re_rank)
        actions.addWidget(self._analyze_selected)
        actions.addStretch(1)
        actions.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(hint)
        layout.addWidget(self._splitter, stretch=1)
        layout.addLayout(actions)

        self._restore_state()
        self.reload()

    def _restore_state(self) -> None:
        geometry = self._settings.value("review/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self._settings.value("review/splitter")
        if splitter_state is not None:
            self._splitter.restoreState(splitter_state)

    def _save_state(self) -> None:
        self._settings.setValue("review/geometry", self.saveGeometry())
        self._settings.setValue("review/splitter", self._splitter.saveState())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._is_busy():
            event.ignore()
            QMessageBox.information(
                self,
                "Busy",
                "Wait for the current photo analysis to finish.",
            )
            return
        self._save_state()
        super().closeEvent(event)

    def done(self, result: int) -> None:  # noqa: D401
        self._save_state()
        super().done(result)

    def reload(self) -> None:
        photos = self._repo.list_photos()
        # Prefer existing manual_order when present.
        if any(photo.manual_order is not None for photo in photos):
            photos = sorted(
                photos,
                key=lambda photo: (
                    photo.manual_order is None,
                    photo.manual_order if photo.manual_order is not None else 10**9,
                    photo.sort_score if photo.sort_score is not None else float("inf"),
                    str(photo.original_path).lower(),
                ),
            )
        self._timeline.set_photos(photos)
        self._dirty_order = False

    def _on_order_changed(self, _photos: list[PhotoRecord]) -> None:
        self._dirty_order = True

    def _on_photo_updated(self, photo: PhotoRecord) -> None:
        self._timeline.refresh_item(photo)
        # Keep master list age/status in sync for later save-order.
        for index, current in enumerate(self._timeline._photos):
            if current.id == photo.id:
                self._timeline._photos[index] = photo
                break

    def _save_order(self) -> None:
        ordered = self._timeline.photos_in_visual_order()
        if self._timeline._filter != ReviewFilter.ALL:
            QMessageBox.information(
                self,
                "Filter Active",
                "Switch filter to “All photos” before saving a full custom order.\n"
                "Or use Re-rank by Ages.",
            )
            return

        for index, photo in enumerate(ordered):
            photo.manual_order = index
            photo.review_status = (
                ReviewStatus.MANUALLY_CORRECTED
                if photo.review_status
                not in {ReviewStatus.EXCLUDED, ReviewStatus.APPROVED}
                else photo.review_status
            )
            photo.sort_score = float(index)
            self._repo.upsert(photo)
        self._dirty_order = False
        QMessageBox.information(
            self,
            "Order Saved",
            f"Saved custom order for {len(ordered)} photos.\n"
            "Export will use this order.",
        )
        self.reload()

    def _rerank_by_ages(self) -> None:
        photos = self._repo.list_photos()
        for photo in photos:
            photo.manual_order = None
        ranked = rank_photo_records(photos, date_of_birth=self._date_of_birth)
        for photo in ranked:
            self._repo.upsert(photo)
        self._dirty_order = False
        self.reload()
        QMessageBox.information(
            self,
            "Re-ranked",
            "Cleared custom order and re-ranked by age signals.\n"
            "AI ages above the subject’s maximum age from date of birth "
            "were clamped.",
        )

    def _analyze_selected_photos(self) -> None:
        if self._is_busy():
            QMessageBox.information(
                self,
                "Busy",
                "Wait for the current photo analysis to finish.",
            )
            return
        selected = self._timeline.selected_photos()
        if not selected:
            QMessageBox.information(
                self,
                "No Photo Selected",
                "Select one or more photos in the timeline, then click "
                "Re-analyze Selected.",
            )
            return
        if not self._reference_photos:
            QMessageBox.warning(
                self,
                "No Reference Photos",
                "Add reference photos to the project before re-analyzing.",
            )
            return

        photo_ids = [photo.id for photo in selected if photo.id is not None]
        if not photo_ids:
            QMessageBox.warning(
                self,
                "Cannot Analyze",
                "Selected photos are missing database IDs. Run Analyze Photos "
                "from the main window first.",
            )
            return

        label = selected[0].original_path.name
        if len(photo_ids) == 1:
            message = f"Re-analyzing {label}…"
        else:
            message = f"Re-analyzing {len(photo_ids)} photos…"

        progress = QProgressDialog(message, None, 0, len(photo_ids), self)
        progress.setWindowTitle("Analyze Photo")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self._progress = progress

        thread = QThread(self)
        worker = _SinglePhotoWorker(
            project_id=self._project_id,
            reference_photos=self._reference_photos,
            date_of_birth=self._date_of_birth,
            photo_ids=photo_ids,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_single_progress)
        worker.finished.connect(self._on_single_finished)
        worker.error.connect(self._on_single_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_single_thread_finished)

        self._analyze_selected.setEnabled(False)
        self._worker_thread = thread
        self._worker = worker
        thread.start()

    def _on_single_progress(self, current: int, total: int, message: str) -> None:
        if self._progress is None:
            return
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(current)
        self._progress.setLabelText(message)

    def _on_single_finished(self, _updated: list) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self.reload()
        # Reselect first updated photo if possible.
        selected = self._timeline.selected_photos()
        if selected:
            self._details.set_photo(selected[0])
        QMessageBox.information(
            self,
            "Analysis Complete",
            "Finished re-analyzing the selected photo(s).",
        )

    def _on_single_error(self, message: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        QMessageBox.critical(self, "Analysis Failed", message)

    def _on_single_thread_finished(self) -> None:
        self._worker_thread = None
        self._worker = None
        self._analyze_selected.setEnabled(True)

    def _is_busy(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.isRunning()

    def _on_close(self) -> None:
        if self._is_busy():
            QMessageBox.information(
                self,
                "Busy",
                "Wait for the current photo analysis to finish.",
            )
            return
        if self._dirty_order:
            answer = QMessageBox.question(
                self,
                "Unsaved Order",
                "You dragged photos but did not save the order. Close anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()
