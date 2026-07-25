"""Main application window for ChronoFace."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, QProcess, QSettings, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShowEvent, QUndoStack
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.commands import ProjectConfigCommand, copy_project
from src.database.photo_repository import PhotoRepository
from src.database.repository import ProjectRepository
from src.domain.models import ProjectConfig, ScanSummary
from src.export.file_exporter import ExportResult, classify_photo
from src.ui.analysis_complete_dialog import AnalysisCompleteDialog
from src.ui.dashboard_page import DashboardPage
from src.ui.export_complete_dialog import ExportCompleteDialog
from src.ui.export_dialog import ExportDialog
from src.ui.project_setup_dialog import ProjectSetupPage
from src.ui.sidebar import AppSidebar
from src.ui.welcome_view import WelcomeView, _format_last_opened
from src.ui.message_dialog import ChoiceDialog, MessageDialog
from src.settings.app_settings import AppSettings, load_settings
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

_PAGE_PROJECTS = 0
_PAGE_DASHBOARD = 1
_PAGE_SETTINGS = 2
_PAGE_SETUP = 3


class _VisionWarmWorker(QObject):
    """Preload torch / MiVOLO imports so first Analyze or Settings probe is faster."""

    finished = Signal()

    def run(self) -> None:
        try:
            from src.vision.mivolo_age import mivolo_deps_present, warm_mivolo_imports

            if mivolo_deps_present():
                warm_mivolo_imports()
        except Exception:  # noqa: BLE001
            pass
        self.finished.emit()


class MainWindow(QMainWindow):
    """Top-level shell: sidebar + projects list + project dashboard."""

    def __init__(self, repository: ProjectRepository | None = None) -> None:
        super().__init__()
        self.setWindowTitle("ChronoFace")
        self.setMinimumSize(QSize(1100, 700))
        self.resize(1400, 900)

        self._repository = repository or ProjectRepository()
        self._project: ProjectConfig | None = None
        self._worker_thread: QThread | None = None
        self._worker: AnalysisWorker | None = None
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._settings = QSettings("ChronoFace", "ChronoFace")
        self._restart_after_close = False
        self._undo_stack = QUndoStack(self)
        self._undo_stack.setUndoLimit(100)
        self._undo_stack.indexChanged.connect(self._on_undo_index_changed)
        self._settings_page = None  # built lazily — avoids torch at startup
        self._warm_thread: QThread | None = None
        self._warm_started = False

        self._build_menu()
        self._build_ui()
        self._restore_window_state()
        self._apply_display_settings()
        self._show_projects()
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

        edit_project_action = QAction("Edit Project…", self)
        edit_project_action.triggered.connect(self.edit_project)
        file_menu.addAction(edit_project_action)

        close_action = QAction("Close Project", self)
        close_action.setShortcut("Ctrl+W")
        close_action.triggered.connect(self.close_project)
        file_menu.addAction(close_action)

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

        file_menu.addSeparator()

        save_order_action = QAction("Save Current Order", self)
        save_order_action.triggered.connect(self._save_dashboard_order)
        file_menu.addAction(save_order_action)

        rerank_action = QAction("Re-rank by Ages", self)
        rerank_action.triggered.connect(self._rerank_dashboard)
        file_menu.addAction(rerank_action)

        file_menu.addSeparator()

        restart_action = QAction("Restart", self)
        restart_action.setShortcut("Ctrl+Shift+R")
        restart_action.setToolTip("Quit and reopen ChronoFace")
        restart_action.triggered.connect(self.restart_application)
        file_menu.addAction(restart_action)

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        self._undo_action = self._undo_stack.createUndoAction(self, "Undo")
        self._undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self._undo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        edit_menu.addAction(self._undo_action)

        self._redo_action = self._undo_stack.createRedoAction(self, "Redo")
        self._redo_action.setShortcuts(
            [
                QKeySequence("Ctrl+Shift+Z"),
                QKeySequence("Ctrl+Y"),
            ]
        )
        self._redo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        edit_menu.addAction(self._redo_action)

        settings_menu = self.menuBar().addMenu("&Settings")
        open_settings = QAction("Preferences…", self)
        open_settings.setShortcut("Ctrl+,")
        open_settings.triggered.connect(self.open_settings)
        settings_menu.addAction(open_settings)

        help_menu = self.menuBar().addMenu("&Help")
        privacy_action = QAction("Privacy", self)
        privacy_action.triggered.connect(self.show_privacy)
        help_menu.addAction(privacy_action)

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _build_ui(self) -> None:
        self._sidebar = AppSidebar()
        self._sidebar.navigate.connect(self._on_sidebar_navigate)

        self._welcome_view = WelcomeView()
        self._welcome_view.create_project_requested.connect(self.new_project)
        self._welcome_view.open_project_requested.connect(self._open_project_by_id)

        self._dashboard = DashboardPage()
        self._dashboard.set_undo_stack(self._undo_stack)
        self._dashboard.edit_project_requested.connect(self.edit_project)
        self._dashboard.analyze_requested.connect(self.start_metadata_scan)
        self._dashboard.export_requested.connect(self.start_export)
        self._dashboard.status_message.connect(self.statusBar().showMessage)
        self._dashboard.processing_bar.cancel_requested.connect(self._cancel_scan)

        # Settings is created on first open so startup skips torch / MiVOLO probes.
        self._settings_host = QWidget()
        self._settings_host_layout = QVBoxLayout(self._settings_host)
        self._settings_host_layout.setContentsMargins(0, 0, 0, 0)
        self._settings_host_layout.setSpacing(0)
        self._settings_return_page = _PAGE_PROJECTS

        self._setup_page = ProjectSetupPage()
        self._setup_page.saved.connect(self._on_setup_saved)
        self._setup_page.deleted.connect(self._on_setup_deleted)
        self._setup_page.cancelled.connect(self._leave_setup)
        self._setup_return_page = _PAGE_PROJECTS
        self._setup_edit_before: ProjectConfig | None = None

        self._stack = QStackedWidget()
        self._stack.addWidget(self._welcome_view)
        self._stack.addWidget(self._dashboard)
        self._stack.addWidget(self._settings_host)
        self._stack.addWidget(self._setup_page)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._sidebar)
        content_layout.addWidget(self._stack, stretch=1)

        self.setCentralWidget(content)
        self.setStatusBar(QStatusBar())

    def _on_sidebar_navigate(self, key: str) -> None:
        if key == "settings":
            self.open_settings()
            return
        if key == "projects":
            self._show_projects(refresh=True)
            return
        if key == "dashboard":
            if self._project is None:
                MessageDialog.information(
                    self,
                    "No Project Open",
                    "Open or create a project to view the dashboard.",
                )
                self._sidebar.set_active("projects")
                return
            self._stack.setCurrentIndex(_PAGE_DASHBOARD)
            self._sidebar.set_active("dashboard")

    def _show_projects(self, *, refresh: bool = True) -> None:
        if refresh:
            recent = self._repository.list_recent()
            self._welcome_view.set_recent_projects(recent)
        self._stack.setCurrentIndex(_PAGE_PROJECTS)
        self._sidebar.set_active("projects")
        self._sidebar.set_dashboard_enabled(self._project is not None)
        if self._project is None:
            recent = self._repository.list_recent()
            if recent:
                self.statusBar().showMessage(
                    f"Last project: {recent[0]['name']} — click it to open"
                )
            else:
                self.statusBar().showMessage("Create a new project to get started")

    def new_project(self) -> None:
        if self._is_busy():
            MessageDialog.warning(self, "Busy", "Wait for the current task to finish.")
            return
        current = self._stack.currentIndex()
        if current != _PAGE_SETUP:
            self._setup_return_page = current
        self._setup_edit_before = None
        self._setup_page.prepare_new()
        self._stack.setCurrentIndex(_PAGE_SETUP)
        self._sidebar.set_active("projects")
        self.statusBar().showMessage("Create a new project")

    def edit_project(self) -> None:
        if self._is_busy():
            MessageDialog.warning(self, "Busy", "Wait for the current task to finish.")
            return
        if self._project is None:
            MessageDialog.information(
                self,
                "No Project Open",
                "Create or open a project before editing.",
            )
            return
        current = self._stack.currentIndex()
        if current != _PAGE_SETUP:
            self._setup_return_page = current
        self._setup_edit_before = copy_project(self._project)
        self._setup_page.prepare_edit(self._project)
        self._stack.setCurrentIndex(_PAGE_SETUP)
        self._sidebar.set_active("dashboard")
        self.statusBar().showMessage(f"Editing project: {self._project.name}")

    def _on_setup_saved(self, config: ProjectConfig) -> None:
        if self._setup_edit_before is None:
            try:
                saved = self._repository.create(config)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to create project")
                MessageDialog.critical(self, "Could Not Create Project", str(exc))
                return
            self._set_project(saved)
            self.statusBar().showMessage(
                f"Project '{saved.name}' created — click Analyze Photos to start"
            )
            MessageDialog.information(
                self,
                "Project Created",
                f"Project '{saved.name}' was saved.\n\n"
                "Click Analyze Photos to scan metadata and match faces locally.",
            )
            return

        before = self._setup_edit_before
        after = copy_project(config)
        try:
            self._undo_stack.push(
                ProjectConfigCommand(
                    before,
                    after,
                    "Edit project",
                    repository=self._repository,
                    on_applied=self._on_project_config_applied,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to update project")
            MessageDialog.critical(self, "Could Not Save Project", str(exc))
            return
        self._setup_edit_before = None
        self._leave_setup()

    def _on_setup_deleted(self) -> None:
        before = self._setup_edit_before
        if before is None and self._project is not None:
            before = copy_project(self._project)
        if before is None:
            self._leave_setup()
            return
        project_id = before.id
        name = before.name
        try:
            self._repository.delete(project_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to delete project %s", project_id)
            MessageDialog.critical(self, "Could Not Delete Project", str(exc))
            return
        self._setup_edit_before = None
        self._clear_project()
        self.statusBar().showMessage(
            f"Deleted project: {name} — original photos were kept"
        )
        logger.info("Deleted project %s", project_id)

    def _leave_setup(self) -> None:
        self._setup_edit_before = None
        page = self._setup_return_page
        if page == _PAGE_DASHBOARD and self._project is not None:
            self._stack.setCurrentIndex(_PAGE_DASHBOARD)
            self._sidebar.set_active("dashboard")
            return
        if page == _PAGE_SETTINGS:
            self.open_settings()
            return
        self._show_projects(refresh=False)

    def restart_application(self) -> None:
        self._restart_after_close = True
        self.close()

    @staticmethod
    def _launch_new_instance() -> bool:
        program = sys.executable
        args = sys.argv[1:] if getattr(sys, "frozen", False) else list(sys.argv)
        started = QProcess.startDetached(program, args, os.getcwd())
        ok = started[0] if isinstance(started, tuple) else bool(started)
        if not ok:
            logger.error("Failed to relaunch ChronoFace (%s %s)", program, args)
        return ok

    def close_project(self) -> None:
        if self._project is None:
            MessageDialog.information(
                self,
                "No Project Open",
                "There is no project to close.",
            )
            return
        if self._is_busy():
            MessageDialog.warning(
                self,
                "Busy",
                "Wait for the current analysis or export to finish before closing.",
            )
            return

        name = self._project.name
        project_id = self._project.id
        try:
            self._repository.load(project_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not refresh recent index while closing project %s",
                project_id,
            )

        self._clear_project()
        self.statusBar().showMessage(
            f"Closed project: {name} — all progress is saved"
        )
        logger.info("Closed project %s", project_id)

    def _clear_project(self) -> None:
        self._undo_stack.clear()
        self._project = None
        self._dashboard.set_project(None)
        self._dashboard.processing_bar.reset()
        self._sidebar.set_dashboard_enabled(False)
        self._show_projects()

    def open_recent_project(self) -> None:
        if self._is_busy():
            MessageDialog.warning(self, "Busy", "Wait for the current task to finish.")
            return
        recent = self._repository.list_recent()
        if not recent:
            MessageDialog.information(
                self,
                "No Recent Projects",
                "No saved projects yet. Create a new project first.",
            )
            return

        labels = [
            f"{item['name']}  ({_format_last_opened(item['last_opened_at'])})"
            for item in recent
        ]
        choice, ok = ChoiceDialog.get_item(
            self,
            "Open Recent Project",
            "Select a project:",
            labels,
            0,
        )
        if not ok or not choice:
            return
        index = labels.index(choice)
        self._open_project_by_id(recent[index]["id"])

    def _open_project_by_id(self, project_id: str) -> None:
        if self._is_busy():
            MessageDialog.warning(self, "Busy", "Wait for the current task to finish.")
            return
        try:
            config = self._repository.load(project_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to open project %s", project_id)
            MessageDialog.critical(self, "Could Not Open Project", str(exc))
            return
        self._set_project(config)

    def _set_project(self, config: ProjectConfig, *, reset_undo: bool = True) -> None:
        if reset_undo:
            self._undo_stack.clear()
        self._apply_project_ui(config)

    def _on_project_config_applied(self, config: ProjectConfig) -> None:
        self._apply_project_ui(config)

    def _apply_project_ui(self, config: ProjectConfig) -> None:
        self._project = config
        self._dashboard.set_undo_stack(self._undo_stack)
        self._dashboard.set_project(config)
        self._dashboard.set_actions_enabled(True)
        self._sidebar.set_dashboard_enabled(True)
        self._stack.setCurrentIndex(_PAGE_DASHBOARD)
        self._sidebar.set_active("dashboard")
        self.statusBar().showMessage(f"Opened project: {config.name}")
        logger.info("UI loaded project %s", config.id)

    def _on_undo_index_changed(self, _index: int) -> None:
        if self._undo_stack.canUndo():
            self.statusBar().showMessage(
                f"Undo available: {self._undo_stack.undoText()}"
            )
        elif self._undo_stack.canRedo():
            self.statusBar().showMessage(
                f"Redo available: {self._undo_stack.redoText()}"
            )

    def _refresh_dashboard(self) -> None:
        if self._project is not None:
            self._dashboard.reload()

    def _save_dashboard_order(self) -> None:
        if self._project is None:
            return
        self._dashboard.save_order()

    def _rerank_dashboard(self) -> None:
        if self._project is None:
            return
        self._dashboard.rerank_by_ages()

    def start_metadata_scan(self) -> None:
        self._start_analysis(force_face_reprocess=False)

    def start_force_face_reanalysis(self) -> None:
        self._start_analysis(force_face_reprocess=True)

    def _start_analysis(self, *, force_face_reprocess: bool) -> None:
        if self._project is None:
            MessageDialog.information(
                self,
                "No Project Open",
                "Create or open a project before scanning.",
            )
            return
        if self._is_busy():
            MessageDialog.information(
                self,
                "Busy",
                "Wait for the current analysis or export to finish.",
            )
            return
        if not self._project.input_folder.is_dir():
            MessageDialog.warning(
                self,
                "Missing Input Folder",
                f"Input folder does not exist:\n{self._project.input_folder}",
            )
            return

        settings = load_settings()
        needs_reprocess, _, _ = project_needs_face_reprocess(
            self._project.id, settings
        )
        if force_face_reprocess:
            preset = get_preset(settings.resolved_preset_id())
            if not MessageDialog.question(
                self,
                "Scan faces again?",
                f"Every photo will be scanned again with “{preset.title}”.\n\n"
                "This may take a few minutes.",
                yes_text="Scan again",
                no_text="Cancel",
            ):
                return
            force_face_reprocess = True
        elif needs_reprocess:
            force_face_reprocess = True

        self._set_action_buttons_enabled(False)
        self._dashboard.processing_bar.start()
        if force_face_reprocess:
            self._dashboard.processing_bar.append_log(
                "Scanning faces again with the current model…"
            )
        self.statusBar().showMessage("Scanning photos…")

        thread = QThread(self)
        worker = AnalysisWorker(
            project_id=self._project.id,
            input_folder=self._project.input_folder,
            date_of_birth=self._project.date_of_birth,
            reference_photos=self._project.reference_photos,
            include_subfolders=self._project.include_subfolders,
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
            MessageDialog.information(
                self,
                "No Project Open",
                "Create or open a project before exporting.",
            )
            return
        if self._is_busy():
            MessageDialog.information(
                self,
                "Busy",
                "Wait for the current analysis or export to finish.",
            )
            return

        photos = PhotoRepository(self._project.id).list_photos()
        if not photos:
            MessageDialog.information(
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
        self._dashboard.processing_bar.start(total_hint=len(photos))
        self._dashboard.processing_bar.append_log(
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
            self._dashboard.processing_bar.append_log("Cancel requested…")

    def _on_scan_progress(self, current: int, total: int, message: str) -> None:
        self._dashboard.processing_bar.update_progress(current, total, message)
        self.statusBar().showMessage(f"Processing photo {current} of {total}")

    def _on_scan_finished(self, summary: object) -> None:
        assert isinstance(summary, ScanSummary)
        self._undo_stack.clear()
        self._dashboard.processing_bar.finish_success(summary)
        self._refresh_dashboard()
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage(
            f"Scan complete — {summary.total_discovered} photos"
        )
        dialog = AnalysisCompleteDialog(summary, self)
        if dialog.exec() == AnalysisCompleteDialog.Review:
            self._dashboard.focus_needs_review()

    def _on_scan_cancelled(self) -> None:
        self._undo_stack.clear()
        self._dashboard.processing_bar.finish_cancelled()
        self._refresh_dashboard()
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage("Scan cancelled")

    def _on_scan_error(self, message: str) -> None:
        self._undo_stack.clear()
        self._dashboard.processing_bar.finish_error(message)
        self._refresh_dashboard()
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage("Scan failed")
        MessageDialog.critical(self, "Scan Failed", message)

    def _on_thread_finished(self) -> None:
        self._worker_thread = None
        self._worker = None
        if self._project is not None and not self._is_exporting():
            self._set_action_buttons_enabled(True)

    def _on_export_progress(self, current: int, total: int, message: str) -> None:
        self._dashboard.processing_bar.update_progress(current, total, message)
        self.statusBar().showMessage(f"Exporting {current} of {total}")

    def _on_export_finished(self, result: object) -> None:
        assert isinstance(result, ExportResult)
        self._dashboard.processing_bar.finish_success_message(
            f"Export complete. Main: {result.exported_main}, "
            f"unresolved: {result.exported_unresolved}, "
            f"excluded: {result.exported_excluded}, "
            f"errors: {len(result.errors)}."
        )
        if result.csv_path is not None:
            self._dashboard.processing_bar.append_log(f"CSV report: {result.csv_path}")
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage(
            f"Export complete — {result.exported_main} photos in output folder"
        )

        ExportCompleteDialog(result, self).exec()

    def _on_export_error(self, message: str) -> None:
        self._dashboard.processing_bar.finish_error(message)
        self._set_action_buttons_enabled(True)
        self.statusBar().showMessage("Export failed")
        MessageDialog.critical(self, "Export Failed", message)

    def _on_export_thread_finished(self) -> None:
        self._export_thread = None
        self._export_worker = None
        if self._project is not None and not self._is_scanning():
            self._set_action_buttons_enabled(True)

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        self._dashboard.set_actions_enabled(enabled and self._project is not None)

    def _is_scanning(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.isRunning()

    def _is_exporting(self) -> bool:
        return self._export_thread is not None and self._export_thread.isRunning()

    def _is_busy(self) -> bool:
        return (
            self._is_scanning()
            or self._is_exporting()
            or self._dashboard._is_local_busy()
        )

    def _apply_display_settings(self) -> None:
        settings = load_settings()
        self._welcome_view.set_privacy_banner_visible(settings.show_privacy_banner)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._warm_started:
            self._warm_started = True
            # Let the first paint finish, then warm ML imports in the background.
            QTimer.singleShot(250, self._start_vision_warm)

    def _start_vision_warm(self) -> None:
        if self._warm_thread is not None:
            return
        thread = QThread(self)
        worker = _VisionWarmWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_warm_thread)
        self._warm_thread = thread
        thread.start()

    def _clear_warm_thread(self) -> None:
        self._warm_thread = None

    def _ensure_settings_page(self):
        """Create SettingsPage on first use (keeps startup free of torch imports)."""
        if self._settings_page is not None:
            return self._settings_page
        from src.ui.settings_dialog import SettingsPage

        page = SettingsPage()
        page.settings_saved.connect(self._on_settings_saved)
        page.cancelled.connect(self._on_settings_cancelled)
        self._settings_host_layout.addWidget(page)
        self._settings_page = page
        return page

    def open_settings(self) -> None:
        if self._is_busy():
            MessageDialog.warning(self, "Busy", "Wait for the current task to finish.")
            if self._stack.currentIndex() == _PAGE_DASHBOARD:
                self._sidebar.set_active("dashboard")
            else:
                self._sidebar.set_active("projects")
            return
        current = self._stack.currentIndex()
        if current != _PAGE_SETTINGS:
            self._settings_return_page = current
        page = self._ensure_settings_page()
        page.reload()
        self._stack.setCurrentIndex(_PAGE_SETTINGS)
        self._sidebar.set_active("settings")

    def _on_settings_saved(self, saved: AppSettings) -> None:
        self._apply_display_settings()
        preset = get_preset(saved.resolved_preset_id())
        self.statusBar().showMessage(f"Settings saved — model: {preset.short_label}")

    def _on_settings_cancelled(self) -> None:
        self._leave_settings()

    def _leave_settings(self) -> None:
        page = self._settings_return_page
        if page == _PAGE_DASHBOARD and self._project is not None:
            self._stack.setCurrentIndex(_PAGE_DASHBOARD)
            self._sidebar.set_active("dashboard")
            return
        self._show_projects(refresh=False)

    def show_privacy(self) -> None:
        MessageDialog.information(self, "Privacy", PRIVACY_TEXT)

    def show_about(self) -> None:
        MessageDialog.about(
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

    def _save_window_state(self) -> None:
        self._settings.setValue("main/geometry", self.saveGeometry())
        self._settings.setValue("main/window_state", self.saveState())
        self._dashboard.save_state()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_window_state()
        if self._is_busy():
            if not MessageDialog.question(
                self,
                "Task In Progress",
                "A scan or export is still running. Exit anyway?",
                yes_text="Exit",
                no_text="Stay",
                dangerous=True,
            ):
                self._restart_after_close = False
                event.ignore()
                return
            self._cancel_scan()
            if self._worker_thread is not None:
                self._worker_thread.quit()
                self._worker_thread.wait(3000)
            if self._export_thread is not None:
                self._export_thread.quit()
                self._export_thread.wait(3000)
        if self._restart_after_close:
            if not self._launch_new_instance():
                self._restart_after_close = False
                MessageDialog.warning(
                    self,
                    "Restart Failed",
                    "Could not relaunch ChronoFace. The current window will stay open.",
                )
                event.ignore()
                return
            logger.info("Application restarting")
        else:
            logger.info("Application closing")
        event.accept()
