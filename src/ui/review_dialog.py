"""Full-window manual review workspace."""

from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from PySide6.QtCore import QObject, QSettings, QSize, QThread, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.commands import BulkPhotosSnapshotCommand, copy_photos
from src.database.photo_repository import PhotoRepository
from src.database.repository import ProjectRepository
from src.domain.models import DateReliability, PhotoRecord, ReferencePhoto, ReviewStatus
from src.metadata.age_from_dob import age_from_dob_and_capture
from src.sorting.ranking import rank_photo_records
from src.ui.photo_details_panel import PhotoDetailsPanel
from src.ui.review_timeline import STATUS_LEGEND, ReviewFilter, ReviewTimeline
from src.ui.message_dialog import MessageDialog, ProgressDialog
from src.workers.face_pipeline import FaceAnalysisPipeline, FacePipelineConfig

_LAYOUT_MARGIN = 8
_LAYOUT_SPACING = 8
_SPLITTER_GAP = 16
_BUTTON_STYLE = (
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


class _SinglePhotoWorker(QObject):
    """Re-run face analysis for one or more selected photos."""

    progress = Signal(int, int, str)
    finished = Signal(list)  # list[PhotoRecord]
    cancelled = Signal()
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
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

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
                should_cancel=lambda: self._cancel_requested,
            )
            if self._cancel_requested:
                self.cancelled.emit()
                return
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
        undo_stack: QUndoStack | None = None,
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
        self._undo_stack = undo_stack
        self._dirty_order = False
        self._settings = QSettings("ChronoFace", "ChronoFace")
        self._worker_thread: QThread | None = None
        self._worker: _SinglePhotoWorker | None = None
        self._progress: ProgressDialog | None = None

        help_banner = self._build_help_banner()

        self._timeline = ReviewTimeline()
        self._timeline.set_date_of_birth(date_of_birth)
        self._details = PhotoDetailsPanel()
        self._details.set_project_context(
            project_id,
            date_of_birth,
            undo_stack=undo_stack,
        )

        self._timeline.selection_changed.connect(self._details.set_photo)
        self._timeline.order_changed.connect(self._on_order_changed)
        self._timeline.remove_requested.connect(self._on_remove_requested)
        self._details.remove_requested.connect(self._on_remove_requested)
        self._details.photo_updated.connect(self._on_photo_updated)
        self._details.analyze_requested.connect(self._analyze_selected_photos)

        save_order = QPushButton("Save Current Order")
        save_order.setStyleSheet(_BUTTON_STYLE)
        save_order.clicked.connect(self._save_order)

        re_rank = QPushButton("Re-rank by Ages")
        re_rank.setStyleSheet(_BUTTON_STYLE)
        re_rank.clicked.connect(self._rerank_by_ages)

        self._analyze_selected = QPushButton("Re-analyze Selected")
        self._analyze_selected.setStyleSheet(_BUTTON_STYLE)
        self._analyze_selected.setToolTip(
            "Re-detect faces and estimate a separate AI age for each face "
            "in the selected photo(s)"
        )
        self._analyze_selected.clicked.connect(self._analyze_selected_photos)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_BUTTON_STYLE)
        close_btn.clicked.connect(self._on_close)

        undo_btn = QPushButton("Undo")
        undo_btn.setStyleSheet(_BUTTON_STYLE)
        redo_btn = QPushButton("Redo")
        redo_btn.setStyleSheet(_BUTTON_STYLE)
        if undo_stack is not None:
            undo_action = undo_stack.createUndoAction(self, "Undo")
            # Single binding only — duplicate Ctrl+Z entries become ambiguous.
            undo_action.setShortcut(QKeySequence("Ctrl+Z"))
            undo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.addAction(undo_action)
            undo_btn.clicked.connect(undo_stack.undo)
            undo_btn.setEnabled(undo_stack.canUndo())
            undo_stack.canUndoChanged.connect(undo_btn.setEnabled)

            redo_action = undo_stack.createRedoAction(self, "Redo")
            redo_action.setShortcuts(
                [
                    QKeySequence("Ctrl+Shift+Z"),
                    QKeySequence("Ctrl+Y"),
                ]
            )
            redo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.addAction(redo_action)
            redo_btn.clicked.connect(undo_stack.redo)
            redo_btn.setEnabled(undo_stack.canRedo())
            undo_stack.canRedoChanged.connect(redo_btn.setEnabled)
        else:
            undo_btn.setEnabled(False)
            redo_btn.setEnabled(False)

        # Two equal column shells: matching header height so Filter and
        # "Photo details" share one baseline, and content tops align.
        left_pane = self._build_column_pane(
            header=self._timeline.header_bar,
            body=self._timeline,
        )
        right_pane = self._build_column_pane(
            header=self._build_details_header(),
            body=self._details,
            content_margins=(8, 0, 0, 0),
        )

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(_SPLITTER_GAP)
        self._splitter.setStyleSheet(
            "QSplitter::handle:horizontal {"
            "  background: transparent;"
            "  margin: 0 4px;"
            "}"
        )
        self._splitter.addWidget(left_pane)
        self._splitter.addWidget(right_pane)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([720, 400])

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(_LAYOUT_SPACING)
        actions.addWidget(save_order)
        actions.addWidget(re_rank)
        actions.addWidget(self._analyze_selected)
        actions.addWidget(undo_btn)
        actions.addWidget(redo_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            _LAYOUT_MARGIN, _LAYOUT_MARGIN, _LAYOUT_MARGIN, _LAYOUT_MARGIN
        )
        layout.setSpacing(_LAYOUT_SPACING)
        layout.addWidget(help_banner)
        layout.addWidget(self._splitter, stretch=1)
        layout.addLayout(actions)

        self._restore_state()
        self.reload()

    @staticmethod
    def _build_column_pane(
        *,
        header: QWidget,
        body: QWidget,
        content_margins: tuple[int, int, int, int] = (0, 0, 0, 0),
    ) -> QWidget:
        """One splitter column: fixed header row + body, 8px gap."""
        pane = QWidget()
        pane_layout = QVBoxLayout(pane)
        pane_layout.setContentsMargins(*content_margins)
        pane_layout.setSpacing(_LAYOUT_SPACING)
        pane_layout.addWidget(header)
        pane_layout.addWidget(body, stretch=1)
        return pane

    @staticmethod
    def _build_details_header() -> QWidget:
        header = QWidget()
        header.setFixedHeight(ReviewTimeline.HEADER_HEIGHT)
        header.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(_LAYOUT_SPACING)
        title = QLabel("Photo details")
        title.setStyleSheet("font-weight: 600;")
        title.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        row.addWidget(title)
        row.addStretch(1)
        return header

    @staticmethod
    def _build_help_banner() -> QWidget:
        """Compact instructions + color legend for status chips."""
        banner = QFrame()
        banner.setObjectName("reviewHelpBanner")
        banner.setStyleSheet(
            "#reviewHelpBanner {"
            "  background: #f3f4f6;"
            "  border: 1px solid #d8dbe0;"
            "  border-radius: 4px;"
            "}"
        )
        banner.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )

        how_title = QLabel("How to review")
        how_title.setStyleSheet("font-weight: 600; background: transparent;")

        how_body = QLabel(
            "1. Drag thumbnails to set order (youngest → oldest).\n"
            "2. Select a photo to edit age, re-analyze, approve, remove, "
            "or mark as not the target.\n"
            "3. Click the Photo details preview to view it larger.\n"
            "4. Hover the photo grid and use Ctrl + / − or Ctrl + mouse wheel "
            "to resize thumbnails."
        )
        how_body.setWordWrap(True)
        how_body.setStyleSheet("background: transparent; color: #333;")

        legend_label = QLabel("Status colors")
        legend_label.setStyleSheet("font-weight: 600; background: transparent;")

        legend_row = QHBoxLayout()
        legend_row.setContentsMargins(0, 0, 0, 0)
        legend_row.setSpacing(_LAYOUT_SPACING)
        for color, label in STATUS_LEGEND:
            chip = QLabel(label)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setStyleSheet(
                f"QLabel {{"
                f"  background: {color};"
                f"  color: white;"
                f"  padding: 3px 10px;"
                f"  border-radius: 3px;"
                f"}}"
            )
            legend_row.addWidget(chip)
        legend_row.addStretch(1)

        layout = QVBoxLayout(banner)
        layout.setContentsMargins(_LAYOUT_MARGIN, _LAYOUT_MARGIN, _LAYOUT_MARGIN, _LAYOUT_MARGIN)
        layout.setSpacing(6)
        layout.addWidget(how_title)
        layout.addWidget(how_body)
        layout.addWidget(legend_label)
        layout.addLayout(legend_row)
        return banner

    def _restore_state(self) -> None:
        geometry = self._settings.value("review/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self._settings.value("review/splitter")
        if splitter_state is not None:
            self._splitter.restoreState(splitter_state)
        thumb_index = self._settings.value("review/thumb_index")
        if thumb_index is not None:
            try:
                self._timeline.set_thumb_index(int(thumb_index))
            except (TypeError, ValueError):
                pass

    def _save_state(self) -> None:
        self._settings.setValue("review/geometry", self.saveGeometry())
        self._settings.setValue("review/splitter", self._splitter.saveState())
        self._settings.setValue("review/thumb_index", self._timeline.thumb_index)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._is_busy():
            event.ignore()
            MessageDialog.information(
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

    def _on_remove_requested(self, photo: PhotoRecord) -> None:
        if not MessageDialog.question(
            self,
            "Remove from Project",
            f"Remove this photo from the project?\n\n{photo.original_path.name}",
            informative="The original file stays on disk. It will not be exported.",
            yes_text="Remove",
            no_text="Cancel",
            dangerous=True,
            default_yes=False,
        ):
            return
        self._details.set_photo(photo)
        self._details.remove_current_photo()

    def _on_photo_updated(self, photo: PhotoRecord) -> None:
        self._timeline.apply_photo_update(photo)

    def _save_order(self) -> None:
        ordered = self._timeline.photos_in_visual_order()
        if self._timeline._filter != ReviewFilter.ALL:
            MessageDialog.information(
                self,
                "Filter Active",
                "Switch filter to “All photos” before saving a full custom order.\n"
                "Or use Re-rank by Ages.",
            )
            return

        before = copy_photos(ordered)
        after = copy_photos(ordered)
        for index, photo in enumerate(after):
            photo.manual_order = index
            photo.review_status = (
                ReviewStatus.MANUALLY_CORRECTED
                if photo.review_status
                not in {ReviewStatus.EXCLUDED, ReviewStatus.APPROVED}
                else photo.review_status
            )
            photo.sort_score = float(index)

        def on_applied(_photos: list[PhotoRecord]) -> None:
            self._dirty_order = False
            self.reload()

        if self._undo_stack is not None:
            self._undo_stack.push(
                BulkPhotosSnapshotCommand(
                    self._project_id,
                    before,
                    after,
                    "Save custom order",
                    on_applied=on_applied,
                )
            )
        else:
            for photo in after:
                self._repo.upsert(photo)
            on_applied(after)

        MessageDialog.information(
            self,
            "Order Saved",
            f"Saved custom order for {len(after)} photos.\n"
            "Export will use this order.",
        )

    def _sync_date_of_birth_from_project(self) -> str:
        """
        Reload birth date from current project settings.

        Keeps Review in sync when the user edits DOB after analysis.
        Returns a short note for the completion dialog.
        """
        previous = self._date_of_birth
        try:
            config = ProjectRepository().load(self._project_id)
        except (OSError, FileNotFoundError, ValueError) as exc:
            return (
                "Could not reload project birth date "
                f"({exc}); used the value from when Review opened."
            )

        self._date_of_birth = config.date_of_birth
        self._timeline.set_date_of_birth(config.date_of_birth)
        self._details.set_project_context(
            self._project_id,
            config.date_of_birth,
            undo_stack=self._undo_stack,
        )

        # Keep the main window project object aligned if Review is opened from it.
        parent = self.parent()
        if parent is not None and hasattr(parent, "_project"):
            project = getattr(parent, "_project", None)
            if project is not None and getattr(project, "id", None) == self._project_id:
                project.date_of_birth = config.date_of_birth

        if config.date_of_birth is None:
            if previous is not None:
                return (
                    "Project birth date was cleared — ages from DOB were removed, "
                    "then photos were re-ranked."
                )
            return "No birth date is set on the project."
        if previous != config.date_of_birth:
            return (
                f"Birth date updated to {config.date_of_birth.isoformat()} "
                "from project settings; ages from DOB were recalculated."
            )
        return (
            f"Confirmed birth date {config.date_of_birth.isoformat()} "
            "from project settings; ages from DOB were recalculated."
        )

    @staticmethod
    def _recalculate_ages_from_dob(
        photos: list[PhotoRecord],
        date_of_birth: Optional[date],
    ) -> None:
        """Refresh persisted age_from_dob using the current project DOB."""
        for photo in photos:
            capture = (
                photo.capture_date
                if photo.date_reliability == DateReliability.RELIABLE_EXIF
                else None
            )
            photo.age_from_dob = age_from_dob_and_capture(date_of_birth, capture)

    def _rerank_by_ages(self) -> None:
        dob_note = self._sync_date_of_birth_from_project()
        photos = self._repo.list_photos()
        before = copy_photos(photos)
        after = copy_photos(photos)
        for photo in after:
            photo.manual_order = None
        self._recalculate_ages_from_dob(after, self._date_of_birth)
        after = rank_photo_records(after, date_of_birth=self._date_of_birth)

        def on_applied(_photos: list[PhotoRecord]) -> None:
            self._dirty_order = False
            self.reload()

        if self._undo_stack is not None:
            self._undo_stack.push(
                BulkPhotosSnapshotCommand(
                    self._project_id,
                    before,
                    after,
                    "Re-rank by ages",
                    on_applied=on_applied,
                )
            )
        else:
            for photo in after:
                self._repo.upsert(photo)
            on_applied(after)

        MessageDialog.information(
            self,
            "Re-ranked",
            f"{dob_note}\n\n"
            "Cleared custom order and re-ranked by age signals.\n"
            "AI ages above the subject’s maximum age from date of birth "
            "were clamped.",
        )

    def _analyze_selected_photos(self) -> None:
        if self._is_busy():
            MessageDialog.information(
                self,
                "Busy",
                "Wait for the current photo analysis to finish.",
            )
            return
        selected = self._timeline.selected_photos()
        if not selected:
            MessageDialog.information(
                self,
                "No Photo Selected",
                "Select one or more photos in the timeline, then click "
                "Re-analyze Selected.",
            )
            return
        if not self._reference_photos:
            MessageDialog.warning(
                self,
                "No Reference Photos",
                "Add reference photos to the project before re-analyzing.",
            )
            return

        photo_ids = [photo.id for photo in selected if photo.id is not None]
        if not photo_ids:
            MessageDialog.warning(
                self,
                "Cannot Analyze",
                "Selected photos are missing database IDs. Run Analyze Photos "
                "from the main window first.",
            )
            return

        total = len(photo_ids)
        progress = ProgressDialog(
            self,
            title="Analyze Photo",
            label=self._reanalyze_progress_text(0, total, "Starting…"),
            minimum=0,
            maximum=total,
            cancellable=True,
        )
        progress.setMinimumWidth(480)
        progress.setValue(0)
        progress.cancelled.connect(self._cancel_single_analysis)
        progress.show()
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
        worker.cancelled.connect(self._on_single_cancelled)
        worker.error.connect(self._on_single_error)
        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_single_thread_finished)

        self._analyze_selected.setEnabled(False)
        self._worker_thread = thread
        self._worker = worker
        thread.start()

    @staticmethod
    def _short_progress_name(message: str, max_chars: int = 52) -> str:
        """Keep progress text stable-width; prefer the trailing filename."""
        text = (message or "").strip()
        if text.lower().startswith("re-analyzing"):
            # "Re-analyzing… filename" or "Re-analyzing filename"
            parts = text.replace("…", " ").split(None, 1)
            if len(parts) > 1:
                text = parts[1]
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1] + "…"

    @classmethod
    def _reanalyze_progress_text(
        cls,
        current: int,
        total: int,
        message: str,
    ) -> str:
        total = max(total, 1)
        current = max(0, min(current, total))
        detail = cls._short_progress_name(message)
        return f"{current}/{total} in progress\n{detail}"

    def _on_single_progress(self, current: int, total: int, message: str) -> None:
        if self._progress is None:
            return
        self._progress.setMaximum(max(total, 1))
        # Show completed count on the bar; label shows current/total in progress.
        self._progress.setValue(max(0, current - 1) if current < total else current)
        self._progress.setLabelText(
            self._reanalyze_progress_text(current, total, message)
        )

    def _cancel_single_analysis(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
        if self._progress is not None:
            self._progress.setLabelText("Cancel requested…")
            self._progress.setCancelEnabled(False)

    def _on_single_finished(self, _updated: list) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        if self._undo_stack is not None:
            self._undo_stack.clear()
        self.reload()
        # Reselect first updated photo if possible.
        selected = self._timeline.selected_photos()
        if selected:
            self._details.set_photo(selected[0])
        MessageDialog.information(
            self,
            "Analysis Complete",
            "Finished re-analyzing the selected photo(s).",
        )

    def _on_single_cancelled(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        if self._undo_stack is not None:
            self._undo_stack.clear()
        self.reload()
        selected = self._timeline.selected_photos()
        if selected:
            self._details.set_photo(selected[0])
        MessageDialog.information(
            self,
            "Analysis Cancelled",
            "Re-analysis stopped. Progress already completed was saved.",
        )

    def _on_single_error(self, message: str) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        if self._undo_stack is not None:
            self._undo_stack.clear()
        MessageDialog.critical(self, "Analysis Failed", message)

    def _on_single_thread_finished(self) -> None:
        self._worker_thread = None
        self._worker = None
        self._analyze_selected.setEnabled(True)

    def _is_busy(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.isRunning()

    def _on_close(self) -> None:
        if self._is_busy():
            MessageDialog.information(
                self,
                "Busy",
                "Wait for the current photo analysis to finish.",
            )
            return
        if self._dirty_order:
            if not MessageDialog.question(
                self,
                "Unsaved Order",
                "You dragged photos but did not save the order. Close anyway?",
                yes_text="Close",
                no_text="Stay",
                dangerous=True,
            ):
                return
        self.accept()
