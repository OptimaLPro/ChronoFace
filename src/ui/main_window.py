"""Main application window for ChronoFace."""

from __future__ import annotations

from PySide6.QtCore import QSettings, QSize, Qt, QThread
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.database.photo_repository import PhotoRepository
from src.database.repository import ProjectRepository
from src.domain.models import DateReliability, ProjectConfig, ScanSummary
from src.export.file_exporter import ExportResult, classify_photo
from src.ui.export_dialog import ExportDialog
from src.ui.processing_view import ProcessingView
from src.ui.project_setup_dialog import ProjectSetupDialog
from src.ui.reference_selector import LIFE_STAGE_LABELS
from src.ui.review_dialog import ReviewDialog
from src.ui.settings_dialog import SettingsDialog
from src.ui.welcome_view import WelcomeView
from src.settings.app_settings import load_settings
from src.utils.logging import get_logger
from src.workers.analysis_worker import AnalysisWorker
from src.workers.export_worker import ExportWorker
from src.workers.face_pipeline import project_needs_face_reprocess
from src.vision.model_catalog import get_preset

logger = get_logger("ui.main_window")

PRIVACY_TEXT = (
    "All photo analysis is performed locally on this computer.\n"
    "No photos or facial data are uploaded."
)

_PAGE_WELCOME = 0
_PAGE_WORKSPACE = 1


class MainWindow(QMainWindow):
    """Top-level window: welcome screen, then project workspace."""

    def __init__(self, repository: ProjectRepository | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ChronoFace")
        self.setMinimumSize(QSize(880, 600))
        self.resize(1100, 740)

        self._repository = repository or ProjectRepository()
        self._project: ProjectConfig | None = None
        self._worker_thread: QThread | None = None
        self._worker: AnalysisWorker | None = None
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._settings = QSettings("ChronoFace", "ChronoFace")

        self._build_menu()
        self._build_ui()
        self._restore_window_state()
        self._apply_display_settings()
        self._show_welcome()
        self.statusBar().showMessage("Ready")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction("New Project…", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_project)
        file_menu.addAction(new_action)

        open_action = QAction("Open Recent Project…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_recent_project)
        file_menu.addAction(open_action)

        edit_action = QAction("Edit Project…", self)
        edit_action.triggered.connect(self.edit_project)
        file_menu.addAction(edit_action)

        file_menu.addSeparator()

        scan_action = QAction("Analyze Photos…", self)
        scan_action.setShortcut("Ctrl+R")
        scan_action.triggered.connect(self.start_metadata_scan)
        file_menu.addAction(scan_action)

        force_faces_action = QAction("Re-analyze All Faces…", self)
        force_faces_action.setShortcut("Ctrl+Shift+A")
        force_faces_action.setToolTip(
            "Ignore cached face results and run detection/matching again "
            "with the current model pack"
        )
        force_faces_action.triggered.connect(self.start_force_face_reanalysis)
        file_menu.addAction(force_faces_action)

        export_action = QAction("Export Numbered Photos…", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.start_export)
        file_menu.addAction(export_action)

        review_action = QAction("Review Results…", self)
        review_action.setShortcut("Ctrl+Shift+R")
        review_action.triggered.connect(self.open_review)
        file_menu.addAction(review_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = self.menuBar().addMenu("&Help")
        privacy_action = QAction("Privacy", self)
        privacy_action.triggered.connect(self.show_privacy)
        help_menu.addAction(privacy_action)

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        settings_menu = self.menuBar().addMenu("&Settings")
        open_settings = QAction("Preferences…", self)
        open_settings.setShortcut("Ctrl+,")
        open_settings.triggered.connect(self.open_settings)
        settings_menu.addAction(open_settings)

    def _build_ui(self) -> None:
        self._privacy_banner = QLabel(PRIVACY_TEXT)
        self._privacy_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._privacy_banner.setStyleSheet(
            "QLabel { background: #eef6ee; border: 1px solid #b7d7b7; "
            "padding: 10px; color: #1f4d1f; font-weight: 600; }"
        )

        self._welcome_view = WelcomeView()
        self._welcome_view.create_project_requested.connect(self.new_project)
        self._welcome_view.open_project_requested.connect(self._open_project_by_id)

        self._title_label = QLabel("No project open")
        self._title_label.setStyleSheet("font-size: 20px; font-weight: 600;")

        self._summary_label = QLabel(
            "Create a new project to select an input folder, output folder, "
            "and reference photos of the person to track."
        )
        self._summary_label.setWordWrap(True)

        self._scan_stats_label = QLabel("No photos scanned yet.")
        self._scan_stats_label.setWordWrap(True)

        self._reference_list = QListWidget()
        self._photo_list = QListWidget()

        self._processing_view = ProcessingView()
        self._processing_view.cancel_requested.connect(self._cancel_scan)

        self._phase_note = QLabel(
            "Review corrections, then export numbered copies in age order.\n"
            "Use Review Results to drag-reorder and set manual ages. "
            "Originals are never modified."
        )
        self._phase_note.setWordWrap(True)
        self._phase_note.setStyleSheet(
            "QLabel { background: #f7f7f7; border: 1px solid #ddd; padding: 12px; }"
        )

        new_button = QPushButton("New Project…")
        new_button.clicked.connect(self.new_project)
        open_button = QPushButton("Open Recent…")
        open_button.clicked.connect(self.open_recent_project)
        edit_button = QPushButton("Edit Project…")
        edit_button.clicked.connect(self.edit_project)

        self._analyze_button = QPushButton("Analyze Photos")
        self._analyze_button.setEnabled(False)
        self._analyze_button.setToolTip(
            "Scan metadata, detect faces, and match the target person locally"
        )
        self._analyze_button.clicked.connect(self.start_metadata_scan)

        self._export_button = QPushButton("Export to Folder")
        self._export_button.setEnabled(False)
        self._export_button.setToolTip(
            "Copy numbered photos into the output folder in youngest-to-oldest order"
        )
        self._export_button.clicked.connect(self.start_export)

        self._review_button = QPushButton("Review Results")
        self._review_button.setEnabled(False)
        self._review_button.setToolTip(
            "Open the thumbnail timeline to fix order and ages"
        )
        self._review_button.clicked.connect(self.open_review)

        button_row = QHBoxLayout()
        button_row.addWidget(new_button)
        button_row.addWidget(open_button)
        button_row.addWidget(edit_button)
        button_row.addStretch(1)
        button_row.addWidget(self._analyze_button)
        button_row.addWidget(self._review_button)
        button_row.addWidget(self._export_button)

        self._reference_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._photo_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._reference_list.setMinimumHeight(60)
        self._photo_list.setMinimumHeight(120)

        left = QWidget()
        left.setMinimumWidth(360)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.addWidget(self._title_label)
        left_layout.addWidget(self._summary_label)
        left_layout.addWidget(self._scan_stats_label)
        left_layout.addWidget(QLabel("Reference photos"))
        left_layout.addWidget(self._reference_list, stretch=1)
        left_layout.addWidget(QLabel("Scanned photos"))
        left_layout.addWidget(self._photo_list, stretch=2)
        left_layout.addLayout(button_row)

        right = QWidget()
        right.setMinimumWidth(300)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.addWidget(self._phase_note)
        right_layout.addWidget(self._processing_view, stretch=1)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(left)
        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([660, 440])

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._splitter)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._welcome_view)
        self._stack.addWidget(workspace)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._privacy_banner)
        layout.addWidget(self._stack, stretch=1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def _show_welcome(self) -> None:
        recent = self._repository.list_recent()
        self._welcome_view.set_recent_projects(recent)
        self._stack.setCurrentIndex(_PAGE_WELCOME)
        if recent:
            self.statusBar().showMessage(
                f"Last project: {recent[0]['name']} — click it below to open"
            )
        else:
            self.statusBar().showMessage("Create a new project to get started")

    def new_project(self) -> None:
        if self._is_busy():
            QMessageBox.warning(self, "Busy", "Wait for the current task to finish.")
            return
        dialog = ProjectSetupDialog(self)
        if dialog.exec() != ProjectSetupDialog.DialogCode.Accepted:
            return
        config = dialog.project_config()
        if config is None:
            return
        try:
            saved = self._repository.create(config)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to create project")
            QMessageBox.critical(self, "Could Not Create Project", str(exc))
            return
        self._set_project(saved)
        QMessageBox.information(
            self,
            "Project Created",
            f"Project '{saved.name}' was saved.\n\n"
            "Click Analyze Photos to scan metadata and match faces locally.",
        )

    def edit_project(self) -> None:
        if self._is_busy():
            QMessageBox.warning(self, "Busy", "Wait for the current task to finish.")
            return
        if self._project is None:
            QMessageBox.information(
                self,
                "No Project Open",
                "Create or open a project before editing.",
            )
            return
        dialog = ProjectSetupDialog(self, existing=self._project)
        if dialog.exec() != ProjectSetupDialog.DialogCode.Accepted:
            return
        config = dialog.project_config()
        if config is None:
            return
        try:
            saved = self._repository.update(config)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to update project")
            QMessageBox.critical(self, "Could Not Save Project", str(exc))
            return
        self._set_project(saved)

    def open_recent_project(self) -> None:
        if self._is_busy():
            QMessageBox.warning(self, "Busy", "Wait for the current task to finish.")
            return
        recent = self._repository.list_recent()
        if not recent:
            QMessageBox.information(
                self,
                "No Recent Projects",
                "No saved projects yet. Create a new project first.",
            )
            return

        from PySide6.QtWidgets import QInputDialog

        labels = [
            f"{item['name']}  ({item['last_opened_at']})" for item in recent
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "Open Recent Project",
            "Select a project:",
            labels,
            0,
            False,
        )
        if not ok or not choice:
            return
        index = labels.index(choice)
        self._open_project_by_id(recent[index]["id"])

    def _open_project_by_id(self, project_id: str) -> None:
        if self._is_busy():
            QMessageBox.warning(self, "Busy", "Wait for the current task to finish.")
            return
        try:
            config = self._repository.load(project_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to open project %s", project_id)
            QMessageBox.critical(self, "Could Not Open Project", str(exc))
            return
        self._set_project(config)

    def _set_project(self, config: ProjectConfig) -> None:
        self._project = config
        self._title_label.setText(config.name)

        dob_text = (
            config.date_of_birth.isoformat()
            if config.date_of_birth is not None
            else "Not set"
        )
        self._summary_label.setText(
            f"Input folder:\n{config.input_folder}\n\n"
            f"Output folder:\n{config.output_folder}\n\n"
            f"Date of birth: {dob_text}\n"
            f"Reference photos: {len(config.reference_photos)}\n"
            f"Project ID: {config.id}"
        )

        self._reference_list.clear()
        for index, reference in enumerate(config.reference_photos):
            stage = LIFE_STAGE_LABELS.get(
                reference.life_stage, reference.life_stage.value
            )
            item = QListWidgetItem(
                f"{index + 1}. {reference.file_path.name} [{stage}]"
            )
            item.setToolTip(str(reference.file_path))
            if not reference.file_path.is_file():
                item.setText(item.text() + "  (missing file)")
            self._reference_list.addItem(item)

        self._analyze_button.setEnabled(True)
        self._export_button.setEnabled(True)
        self._review_button.setEnabled(True)
        self._refresh_photo_list()
        self._stack.setCurrentIndex(_PAGE_WORKSPACE)
        self.statusBar().showMessage(f"Opened project: {config.name}")
        logger.info("UI loaded project %s", config.id)

    def _refresh_photo_list(self) -> None:
        self._photo_list.clear()
        if self._project is None:
            self._scan_stats_label.setText("No photos scanned yet.")
            return

        photo_repo = PhotoRepository(self._project.id)
        stats = photo_repo.summarize()
        self._scan_stats_label.setText(
            f"Scanned photos: {stats['total']}  |  "
            f"Target found: {stats.get('target_found', 0)}  |  "
            f"Not found: {stats.get('target_not_found', 0)}  |  "
            f"No face: {stats.get('no_face', 0)}  |  "
            f"Low confidence: {stats.get('low_confidence', 0)}  |  "
            f"Errors: {stats['errors']}\n"
            f"Reliable EXIF dates: {stats['reliable_date']}  |  "
            f"Weak dates: {stats['weak_date']}  |  "
            f"No date: {stats['no_date']}"
        )

        photos = photo_repo.list_photos()
        for photo in photos[:500]:
            date_text = (
                photo.capture_date.strftime("%Y-%m-%d")
                if photo.capture_date
                else "no date"
            )
            if photo.date_reliability == DateReliability.RELIABLE_EXIF:
                reliability = "EXIF"
            elif photo.date_reliability == DateReliability.WEAK_FILESYSTEM:
                reliability = "weak"
            else:
                reliability = "none"

            if photo.target_found:
                identity = f"match {photo.identity_score:.2f}" if photo.identity_score is not None else "match"
            elif photo.review_status.value == "no_face":
                identity = "no face"
            elif photo.review_status.value == "low_confidence":
                identity = (
                    f"low {photo.identity_score:.2f}"
                    if photo.identity_score is not None
                    else "low"
                )
            elif photo.review_status.value == "target_not_found":
                identity = (
                    f"no match {photo.identity_score:.2f}"
                    if photo.identity_score is not None
                    else "no match"
                )
            else:
                identity = "pending"

            if photo.age_from_dob is not None and photo.date_reliability.value == "reliable_exif":
                age_text = f"age {photo.age_from_dob:.1f} (DOB+EXIF)"
            elif photo.estimated_age is not None:
                age_text = f"age ~{photo.estimated_age:.0f} (AI)"
            elif photo.sort_score is not None:
                age_text = f"score {photo.sort_score:.1f}"
            else:
                age_text = "age ?"

            label = (
                f"{photo.original_path.name}  |  {age_text}  |  "
                f"{date_text} ({reliability})  |  {identity}"
            )
            if photo.error_message:
                label += "  [error]"
            item = QListWidgetItem(label)
            item.setToolTip(str(photo.original_path))
            self._photo_list.addItem(item)

        if len(photos) > 500:
            self._photo_list.addItem(
                QListWidgetItem(f"… and {len(photos) - 500} more (not listed)")
            )

    def start_metadata_scan(self) -> None:
        self._start_analysis(force_face_reprocess=False)

    def start_force_face_reanalysis(self) -> None:
        self._start_analysis(force_face_reprocess=True)

    def _start_analysis(self, *, force_face_reprocess: bool) -> None:
        if self._project is None:
            QMessageBox.information(
                self,
                "No Project Open",
                "Create or open a project before scanning.",
            )
            return
        if self._is_busy():
            QMessageBox.information(
                self,
                "Busy",
                "Wait for the current analysis or export to finish.",
            )
            return
        if not self._project.input_folder.is_dir():
            QMessageBox.warning(
                self,
                "Missing Input Folder",
                f"Input folder does not exist:\n{self._project.input_folder}",
            )
            return

        settings = load_settings()
        needs_reprocess, previous, current = project_needs_face_reprocess(
            self._project.id, settings
        )
        if force_face_reprocess:
            answer = QMessageBox.question(
                self,
                "Re-analyze All Faces",
                "This will ignore cached face results and re-run detection, "
                "matching, and age estimation for every photo with the current "
                f"model pack:\n\n{get_preset(settings.resolved_preset_id()).title}\n\n"
                "Metadata/thumbnails stay cached. Continue?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            force_face_reprocess = True
        elif needs_reprocess:
            preset = get_preset(settings.resolved_preset_id())
            previous_label = previous or "older cache (no model stamp)"
            QMessageBox.information(
                self,
                "Model Changed — Re-analyzing Faces",
                "This project’s faces were analyzed with a different model:\n\n"
                f"Previous: {previous_label}\n"
                f"Current:  {preset.title}\n"
                f"({current})\n\n"
                "Cached face matches will be ignored and all photos will be "
                "re-analyzed with the new model. Metadata can stay skipped "
                "if files are unchanged.\n\n"
                "This can take several minutes on large folders.",
            )
            force_face_reprocess = True

        self._set_action_buttons_enabled(False)
        self._processing_view.start()
        if force_face_reprocess:
            self._processing_view.append_log(
                "Face re-analysis enabled — cached face results will be ignored."
            )
        self.statusBar().showMessage("Scanning photos…")

        thread = QThread(self)
        worker = AnalysisWorker(
            project_id=self._project.id,
            input_folder=self._project.input_folder,
            date_of_birth=self._project.date_of_birth,
            reference_photos=self._project.reference_photos,
            force_reprocess=False,
            force_face_reprocess=force_face_reprocess,
            run_face_analysis=True,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_scan_progress)
        worker.finished.connect(self._on_scan_finished)
        worker.cancelled.connect(self._on_scan_cancelled)
        worker.error.connect(self._on_scan_error)
        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._worker_thread = thread
        self._worker = worker
        thread.start()

    def start_export(self) -> None:
        if self._project is None:
            QMessageBox.information(
                self,
                "No Project Open",
                "Create or open a project before exporting.",
            )
            return
        if self._is_busy():
            QMessageBox.information(
                self,
                "Busy",
                "Wait for the current analysis or export to finish.",
            )
            return

        photos = PhotoRepository(self._project.id).list_photos()
        if not photos:
            QMessageBox.information(
                self,
                "Nothing to Export",
                "Analyze photos first, then export numbered copies.",
            )
            return

        matched = sum(1 for photo in photos if classify_photo(photo) == "main")
        unresolved = sum(1 for photo in photos if classify_photo(photo) == "unresolved")
        excluded = sum(1 for photo in photos if classify_photo(photo) == "excluded")

        dialog = ExportDialog(
            self,
            default_output=self._project.output_folder,
            matched_count=matched,
            unresolved_count=unresolved,
            excluded_count=excluded,
        )
        if dialog.exec() != ExportDialog.DialogCode.Accepted:
            return
        options = dialog.export_options()
        if options is None:
            return

        self._set_action_buttons_enabled(False)
        self._processing_view.start(total_hint=len(photos))
        self._processing_view.append_log(
            f"Exporting numbered copies to:\n{options.output_dir}"
        )
        self.statusBar().showMessage("Exporting photos…")

        thread = QThread(self)
        worker = ExportWorker(
            project_id=self._project.id,
            options=options,
            date_of_birth=self._project.date_of_birth,
            photos=photos,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_export_progress)
        worker.finished.connect(self._on_export_finished)
        worker.error.connect(self._on_export_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_export_thread_finished)

        self._export_thread = thread
        self._export_worker = worker
        thread.start()

    def _cancel_scan(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
            self._processing_view.append_log("Cancel requested…")

    def _on_scan_progress(self, current: int, total: int, message: str) -> None:
        self._processing_view.update_progress(current, total, message)
        self.statusBar().showMessage(f"Processing photo {current} of {total}")

    def _on_scan_finished(self, summary: object) -> None:
        assert isinstance(summary, ScanSummary)
        self._processing_view.finish_success(summary)
        self._refresh_photo_list()
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage(
            f"Scan complete — {summary.total_discovered} photos"
        )
        QMessageBox.information(
            self,
            "Analysis Complete",
            ProcessingView._format_summary(summary)
            + "\n\nPhotos are ranked youngest → oldest.\n"
            "Use Review Results to fix mistakes, then Export to Folder.",
        )

    def _on_scan_cancelled(self) -> None:
        self._processing_view.finish_cancelled()
        self._refresh_photo_list()
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage("Scan cancelled")

    def _on_scan_error(self, message: str) -> None:
        self._processing_view.finish_error(message)
        self._refresh_photo_list()
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage("Scan failed")
        QMessageBox.critical(self, "Scan Failed", message)

    def _on_thread_finished(self) -> None:
        self._worker_thread = None
        self._worker = None
        if self._project is not None and not self._is_exporting():
            self._set_action_buttons_enabled(True)

    def _on_export_progress(self, current: int, total: int, message: str) -> None:
        self._processing_view.update_progress(current, total, message)
        self.statusBar().showMessage(f"Exporting {current} of {total}")

    def _on_export_finished(self, result: object) -> None:
        assert isinstance(result, ExportResult)
        self._processing_view.finish_success_message(
            f"Export complete. Main: {result.exported_main}, "
            f"unresolved: {result.exported_unresolved}, "
            f"excluded: {result.exported_excluded}, "
            f"errors: {len(result.errors)}."
        )
        if result.csv_path is not None:
            self._processing_view.append_log(f"CSV report: {result.csv_path}")
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage(
            f"Export complete — {result.exported_main} photos in output folder"
        )

        details = (
            f"Copied {result.exported_main} numbered photos.\n\n"
            f"Unresolved folder copies: {result.exported_unresolved}\n"
            f"Excluded folder copies: {result.exported_excluded}\n"
        )
        if result.items:
            details = (
                f"Copied {result.exported_main} numbered photos to:\n"
                f"{result.items[0].destination.parent}\n\n"
                f"Unresolved folder copies: {result.exported_unresolved}\n"
                f"Excluded folder copies: {result.exported_excluded}\n"
            )

        if result.csv_path is not None:
            details += f"\nCSV report:\n{result.csv_path}"
        if result.errors:
            details += "\n\nSome files failed:\n" + "\n".join(result.errors[:8])
        QMessageBox.information(self, "Export Complete", details)

    def _on_export_error(self, message: str) -> None:
        self._processing_view.finish_error(message)
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage("Export failed")
        QMessageBox.critical(self, "Export Failed", message)

    def _on_export_thread_finished(self) -> None:
        self._export_thread = None
        self._export_worker = None
        if self._project is not None and not self._is_scanning():
            self._set_action_buttons_enabled(True)

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        has_project = enabled and self._project is not None
        self._analyze_button.setEnabled(has_project)
        self._export_button.setEnabled(has_project)
        self._review_button.setEnabled(has_project)

    def open_review(self) -> None:
        if self._project is None:
            QMessageBox.information(
                self,
                "No Project Open",
                "Create or open a project before reviewing.",
            )
            return
        if self._is_busy():
            QMessageBox.information(
                self,
                "Busy",
                "Wait for the current analysis or export to finish.",
            )
            return
        photos = PhotoRepository(self._project.id).list_photos()
        if not photos:
            QMessageBox.information(
                self,
                "Nothing to Review",
                "Analyze photos first, then open Review Results.",
            )
            return
        dialog = ReviewDialog(
            self,
            project_id=self._project.id,
            date_of_birth=self._project.date_of_birth,
            project_name=self._project.name,
            reference_photos=self._project.reference_photos,
        )
        dialog.exec()
        self._refresh_photo_list()

    def _is_scanning(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.isRunning()

    def _is_exporting(self) -> bool:
        return self._export_thread is not None and self._export_thread.isRunning()

    def _is_busy(self) -> bool:
        return self._is_scanning() or self._is_exporting()

    def _apply_display_settings(self) -> None:
        settings = load_settings()
        self._privacy_banner.setVisible(settings.show_privacy_banner)

    def open_settings(self) -> None:
        if self._is_busy():
            QMessageBox.warning(self, "Busy", "Wait for the current task to finish.")
            return
        dialog = SettingsDialog(self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        self._apply_display_settings()
        saved = dialog.saved_settings()
        if saved is not None:
            from src.vision.model_catalog import get_preset

            preset = get_preset(saved.resolved_preset_id())
            self.statusBar().showMessage(f"Settings saved — model: {preset.short_label}")

    def show_privacy(self) -> None:
        QMessageBox.information(self, "Privacy", PRIVACY_TEXT)

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About ChronoFace",
            "ChronoFace\n"
            "Settings + swappable local model packs\n\n"
            "Sort client photo collections by the age of a specific person "
            "for presentations, slideshows, and other chronological workflows.\n\n"
            "Open Settings to choose OpenCV Fast or InsightFace model packs "
            "(personal / non-commercial).\n\n"
            f"{PRIVACY_TEXT}",
        )

    def _restore_window_state(self) -> None:
        geometry = self._settings.value("main/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        window_state = self._settings.value("main/window_state")
        if window_state is not None:
            self.restoreState(window_state)
        splitter_state = self._settings.value("main/splitter")
        if splitter_state is not None:
            self._splitter.restoreState(splitter_state)

    def _save_window_state(self) -> None:
        self._settings.setValue("main/geometry", self.saveGeometry())
        self._settings.setValue("main/window_state", self.saveState())
        self._settings.setValue("main/splitter", self._splitter.saveState())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_window_state()
        if self._is_busy():
            answer = QMessageBox.question(
                self,
                "Task In Progress",
                "A scan or export is still running. Exit anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._cancel_scan()
            if self._worker_thread is not None:
                self._worker_thread.quit()
                self._worker_thread.wait(3000)
            if self._export_thread is not None:
                self._export_thread.quit()
                self._export_thread.wait(3000)
        logger.info("Application closing")
        event.accept()
