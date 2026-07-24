"""Main project dashboard: metrics, timeline, inspector, needs-review."""

from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import QSettings, QThread, Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.commands import BulkPhotosSnapshotCommand, copy_photos
from src.database.photo_repository import PhotoRepository
from src.database.repository import ProjectRepository
from src.domain.models import DateReliability, PhotoRecord, ProjectConfig, ReviewStatus
from src.metadata.age_from_dob import age_from_dob_and_capture
from src.sorting.ranking import rank_photo_records
from src.ui.age_band_bar import AgeBandBar
from src.ui.metric_card import MetricsRow
from src.ui.needs_review_panel import NeedsReviewPanel, photos_needing_review
from src.ui.photo_details_panel import PhotoDetailsPanel
from src.ui.processing_status_bar import ProcessingStatusBar
from src.ui.project_header import ProjectHeader
from src.ui.review_dialog import _SinglePhotoWorker
from src.ui.review_timeline import ReviewFilter, ReviewTimeline
from src.ui.message_dialog import MessageDialog, ProgressDialog


class DashboardPage(QWidget):
    """Lightroom-style project workspace."""

    edit_project_requested = Signal()
    analyze_requested = Signal()
    export_requested = Signal()
    status_message = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project: ProjectConfig | None = None
        self._repo: PhotoRepository | None = None
        self._undo_stack: QUndoStack | None = None
        self._dirty_order = False
        self._settings = QSettings("ChronoFace", "ChronoFace")
        self._worker_thread: QThread | None = None
        self._worker: _SinglePhotoWorker | None = None
        self._progress: ProgressDialog | None = None
        self._photos: list[PhotoRecord] = []

        self._header = ProjectHeader()
        self._header.edit_requested.connect(self.edit_project_requested.emit)
        self._header.export_requested.connect(self.export_requested.emit)
        self._header.analyze_requested.connect(self.analyze_requested.emit)

        self._metrics = MetricsRow()

        self._timeline = ReviewTimeline()
        self._age_band = AgeBandBar()
        self._needs_review = NeedsReviewPanel()
        self._details = PhotoDetailsPanel()
        self._status_bar = ProcessingStatusBar()

        self._timeline.selection_changed.connect(self._details.set_photo)
        self._timeline.order_changed.connect(self._on_order_changed)
        self._timeline.remove_requested.connect(self._on_remove_requested)
        self._details.remove_requested.connect(self._on_remove_requested)
        self._details.photo_updated.connect(self._on_photo_updated)
        self._details.analyze_requested.connect(self.reanalyze_selected)
        self._needs_review.photo_selected.connect(self._select_photo)
        self._needs_review.review_all_requested.connect(self.focus_needs_review)

        # Timeline toolbar
        section_title = QLabel("Chronological Timeline")
        section_title.setObjectName("sectionTitle")

        self._timeline_view_btn = QPushButton("Timeline View")
        self._timeline_view_btn.setCheckable(True)
        self._timeline_view_btn.setChecked(True)
        self._timeline_view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._grid_view_btn = QPushButton("Grid View")
        self._grid_view_btn.setCheckable(True)
        self._grid_view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._timeline_view_btn.clicked.connect(lambda: self._set_view_mode("timeline"))
        self._grid_view_btn.clicked.connect(lambda: self._set_view_mode("grid"))

        self._save_order_btn = QPushButton("Save Order")
        self._save_order_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_order_btn.clicked.connect(self.save_order)

        self._rerank_btn = QPushButton("Re-rank by Ages")
        self._rerank_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rerank_btn.clicked.connect(self.rerank_by_ages)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        vcenter = Qt.AlignmentFlag.AlignVCenter
        toolbar.addWidget(section_title, 0, vcenter)
        toolbar.addStretch(1)
        toolbar.addWidget(self._timeline.header_bar, 0, vcenter)
        toolbar.addWidget(self._timeline_view_btn, 0, vcenter)
        toolbar.addWidget(self._grid_view_btn, 0, vcenter)
        toolbar.addWidget(self._save_order_btn, 0, vcenter)
        toolbar.addWidget(self._rerank_btn, 0, vcenter)

        timeline_card = QFrame()
        timeline_card.setObjectName("card")
        timeline_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        timeline_layout = QVBoxLayout(timeline_card)
        timeline_layout.setContentsMargins(16, 16, 16, 16)
        timeline_layout.setSpacing(12)
        timeline_layout.addLayout(toolbar)
        timeline_layout.addWidget(self._age_band)
        timeline_layout.addWidget(self._timeline, stretch=1)

        # Equal gutters: layout spacing is reliable; QSplitter handle width is
        # ignored when an app stylesheet is set, so put most of the horizontal
        # gap in the left column's right margin and keep a thin drag handle.
        section_gap = 16
        handle_w = 4

        left_col = QWidget()
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, section_gap - handle_w, 0)
        left_layout.setSpacing(section_gap)
        left_layout.addWidget(timeline_card, stretch=1)
        left_layout.addWidget(self._needs_review)

        inspector_wrap = QFrame()
        inspector_wrap.setObjectName("inspectorCard")
        inspector_wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        inspector_wrap.setMinimumWidth(300)
        inspector_wrap.setMaximumWidth(420)
        inspector_layout = QVBoxLayout(inspector_wrap)
        inspector_layout.setContentsMargins(12, 12, 12, 12)
        inspector_layout.addWidget(self._details)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(handle_w)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background: transparent; }"
            "QSplitter::handle:horizontal {"
            f"  width: {handle_w}px; min-width: {handle_w}px; max-width: {handle_w}px;"
            "}"
        )
        self._splitter.addWidget(left_col)
        self._splitter.addWidget(inspector_wrap)
        self._splitter.setStretchFactor(0, 4)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([900, 340])

        body = QVBoxLayout(self)
        body.setContentsMargins(24, 20, 24, 16)
        body.setSpacing(16)
        body.addWidget(self._header)
        body.addWidget(self._metrics)
        body.addWidget(self._splitter, stretch=1)
        body.addWidget(self._status_bar)

        self._restore_splitter()

    @property
    def processing_bar(self) -> ProcessingStatusBar:
        return self._status_bar

    @property
    def timeline(self) -> ReviewTimeline:
        return self._timeline

    def set_undo_stack(self, undo_stack: QUndoStack) -> None:
        self._undo_stack = undo_stack

    def set_project(self, config: ProjectConfig | None) -> None:
        self._project = config
        self._header.set_project(config)
        if config is None:
            self._repo = None
            self._photos = []
            self._timeline.set_photos([])
            self._needs_review.set_photos([])
            self._metrics.update_stats({})
            self._details.set_photo(None)
            return
        self._repo = PhotoRepository(config.id)
        self._timeline.set_date_of_birth(config.date_of_birth)
        self._needs_review.set_date_of_birth(config.date_of_birth)
        self._details.set_project_context(
            config.id,
            config.date_of_birth,
            undo_stack=self._undo_stack,
        )
        thumb = self._settings.value("dashboard/thumb_index")
        if thumb is not None:
            try:
                self._timeline.set_thumb_index(int(thumb))
            except (TypeError, ValueError):
                pass
        self.reload()

    def set_actions_enabled(self, enabled: bool) -> None:
        has = enabled and self._project is not None
        self._header.set_actions_enabled(has)
        self._save_order_btn.setEnabled(has)
        self._rerank_btn.setEnabled(has)

    def reload(self) -> None:
        if self._repo is None or self._project is None:
            return
        photos = self._repo.list_photos()
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
        self._photos = photos
        self._timeline.set_photos(photos)
        self._needs_review.set_photos(photos)
        self._dirty_order = False
        self._refresh_metrics()

    def _refresh_metrics(self) -> None:
        if self._repo is None:
            self._metrics.update_stats({})
            return
        stats = dict(self._repo.summarize())
        dob = self._project.date_of_birth if self._project else None
        stats["needs_review_total"] = len(
            photos_needing_review(self._photos, dob)
        )
        # Only count reliable EXIF capture dates — not filesystem mtime guesses.
        stats["with_dates"] = stats.get("reliable_date", 0)
        self._metrics.update_stats(stats)

    def focus_needs_review(self) -> None:
        # Show all photos so Unknown-age / low-match items stay visible,
        # then jump selection to the first needs-review card if present.
        combo = self._timeline._filter_combo
        for index in range(combo.count()):
            if combo.itemData(index) == ReviewFilter.ALL.value:
                combo.setCurrentIndex(index)
                break
        items = photos_needing_review(
            self._photos,
            self._project.date_of_birth if self._project else None,
        )
        if items:
            self._select_photo(items[0][0])

    def _select_photo(self, photo: PhotoRecord) -> None:
        for index in range(self._timeline._list.count()):
            item = self._timeline._list.item(index)
            current = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(current, PhotoRecord) and current.id == photo.id:
                self._timeline._list.clearSelection()
                item.setSelected(True)
                self._timeline._list.scrollToItem(item)
                self._details.set_photo(photo)
                return
        self._details.set_photo(photo)

    def _set_view_mode(self, mode: str) -> None:
        timeline_mode = mode == "timeline"
        self._timeline_view_btn.setChecked(timeline_mode)
        self._grid_view_btn.setChecked(not timeline_mode)
        self._age_band.setVisible(timeline_mode)
        if timeline_mode:
            self._timeline.set_thumb_index(max(self._timeline.thumb_index, 2))
        else:
            # Denser grid
            self._timeline.set_thumb_index(min(self._timeline.thumb_index, 1))

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
        for index, current in enumerate(self._photos):
            if current.id == photo.id:
                self._photos[index] = photo
                break
        self._needs_review.set_photos(self._photos)
        self._refresh_metrics()

    def save_order(self) -> None:
        if self._repo is None or self._project is None:
            return
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
                    self._project.id,
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

        self.status_message.emit(f"Saved custom order for {len(after)} photos")
        MessageDialog.information(
            self,
            "Order Saved",
            f"Saved custom order for {len(after)} photos.\n"
            "Export will use this order.",
        )

    def rerank_by_ages(self) -> None:
        if self._repo is None or self._project is None:
            return
        dob_note = self._sync_date_of_birth_from_project()
        photos = self._repo.list_photos()
        before = copy_photos(photos)
        after = copy_photos(photos)
        for photo in after:
            photo.manual_order = None
        self._recalculate_ages_from_dob(after, self._project.date_of_birth)
        after = rank_photo_records(after, date_of_birth=self._project.date_of_birth)

        def on_applied(_photos: list[PhotoRecord]) -> None:
            self._dirty_order = False
            self.reload()

        if self._undo_stack is not None:
            self._undo_stack.push(
                BulkPhotosSnapshotCommand(
                    self._project.id,
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
            "Cleared custom order and re-ranked by age signals.",
        )

    def reanalyze_selected(self) -> None:
        if self._project is None or self._is_local_busy():
            if self._is_local_busy():
                MessageDialog.information(
                    self, "Busy", "Wait for the current photo analysis to finish."
                )
            return
        selected = self._timeline.selected_photos()
        if not selected:
            MessageDialog.information(
                self,
                "No Photo Selected",
                "Select one or more photos, then re-analyze.",
            )
            return
        if not self._project.reference_photos:
            MessageDialog.warning(
                self,
                "No Reference Photos",
                "Add reference photos to the project before re-analyzing.",
            )
            return
        photo_ids = [photo.id for photo in selected if photo.id is not None]
        if not photo_ids:
            return

        total = len(photo_ids)
        progress = ProgressDialog(
            self,
            title="Analyze Photo",
            label="Starting…",
            minimum=0,
            maximum=total,
        )
        progress.setValue(0)
        progress.show()
        self._progress = progress

        thread = QThread(self)
        worker = _SinglePhotoWorker(
            project_id=self._project.id,
            reference_photos=self._project.reference_photos,
            date_of_birth=self._project.date_of_birth,
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
        self._worker_thread = thread
        self._worker = worker
        thread.start()

    def _on_single_progress(self, current: int, total: int, message: str) -> None:
        if self._progress is None:
            return
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(max(0, current - 1) if current < total else current)
        self._progress.setLabelText(f"{current}/{total}\n{message}")

    def _on_single_finished(self, _updated: list) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        if self._undo_stack is not None:
            self._undo_stack.clear()
        self.reload()
        MessageDialog.information(
            self, "Analysis Complete", "Finished re-analyzing the selected photo(s)."
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

    def _is_local_busy(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.isRunning()

    def _sync_date_of_birth_from_project(self) -> str:
        if self._project is None:
            return "No project open."
        previous = self._project.date_of_birth
        try:
            config = ProjectRepository().load(self._project.id)
        except (OSError, FileNotFoundError, ValueError) as exc:
            return f"Could not reload project birth date ({exc})."
        self._project.date_of_birth = config.date_of_birth
        self._timeline.set_date_of_birth(config.date_of_birth)
        self._needs_review.set_date_of_birth(config.date_of_birth)
        self._details.set_project_context(
            self._project.id,
            config.date_of_birth,
            undo_stack=self._undo_stack,
        )
        if config.date_of_birth is None:
            return "No birth date is set on the project."
        if previous != config.date_of_birth:
            return (
                f"Birth date updated to {config.date_of_birth.isoformat()} "
                "from project settings."
            )
        return f"Confirmed birth date {config.date_of_birth.isoformat()}."

    @staticmethod
    def _recalculate_ages_from_dob(
        photos: list[PhotoRecord],
        date_of_birth: Optional[date],
    ) -> None:
        for photo in photos:
            capture = (
                photo.capture_date
                if photo.date_reliability == DateReliability.RELIABLE_EXIF
                else None
            )
            photo.age_from_dob = age_from_dob_and_capture(date_of_birth, capture)

    def save_state(self) -> None:
        self._settings.setValue("dashboard/splitter", self._splitter.saveState())
        self._settings.setValue("dashboard/thumb_index", self._timeline.thumb_index)

    def _restore_splitter(self) -> None:
        state = self._settings.value("dashboard/splitter")
        if state is not None:
            self._splitter.restoreState(state)
