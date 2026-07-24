"""Application Settings dialog — models, matching, downloads."""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.settings.app_settings import AppSettings, load_settings, save_settings
from src.utils.pip_install import pip_install
from src.vision.age_backends import (
    AgeBackendId,
    AgeBackendInfo,
    get_age_backend,
    list_age_backends,
)
from src.vision.insightface_backend import insightface_available, insightface_import_error
from src.vision.mivolo_age import mivolo_available, mivolo_import_error
from src.vision.mivolo_install import install_mivolo_dependencies
from src.vision.model_catalog import (
    BackendFamily,
    ModelPreset,
    ModelPresetId,
    get_preset,
    list_presets,
)
from src.vision.model_manager import (
    describe_install_status,
    ensure_models_for_preset,
)


class _PipInstallWorker(QObject):
    """Runs a pip installer callback off the UI thread."""

    progress = Signal(str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, installer) -> None:
        super().__init__()
        self._installer = installer

    def run(self) -> None:
        try:
            self._installer(on_progress=self.progress.emit)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished.emit()


class SettingsDialog(QDialog):
    """Let the user pick model packs and matching thresholds."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(760, 620)
        self.resize(860, 700)
        self.setSizeGripEnabled(True)

        self._settings = load_settings()
        self._result: AppSettings | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_models_tab(), "Models")
        tabs.addTab(self._build_matching_tab(), "Matching")
        tabs.addTab(self._build_downloads_tab(), "Downloads")
        tabs.addTab(self._build_general_tab(), "General")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save Settings")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self._populate_from_settings()

    def saved_settings(self) -> AppSettings | None:
        return self._result

    def _build_models_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        intro = QLabel(
            "Choose a local model pack. Everything runs on this computer — nothing is uploaded.\n"
            "InsightFace packs are among the best open-source face models and are allowed "
            "for personal / non-commercial use."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._preset_combo = QComboBox()
        for preset in list_presets():
            label = preset.title
            if preset.recommended:
                label += "  ★ recommended"
            self._preset_combo.addItem(label, preset.id.value)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        self._age_combo = QComboBox()
        for backend in list_age_backends():
            label = backend.title
            if backend.recommended:
                label += "  ★ recommended for age"
            self._age_combo.addItem(label, backend.id.value)
        self._age_combo.currentIndexChanged.connect(self._on_age_backend_changed)

        form = QFormLayout()
        form.addRow("Identity model pack", self._preset_combo)
        form.addRow("Age model", self._age_combo)
        layout.addLayout(form)

        self._badge = QLabel()
        self._badge.setWordWrap(True)
        self._badge.setStyleSheet(
            "QLabel { background: #f0f4f8; border: 1px solid #c5d4e3; "
            "padding: 10px; border-radius: 4px; }"
        )
        layout.addWidget(self._badge)

        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setMinimumHeight(220)
        layout.addWidget(self._details, stretch=1)

        self._license = QLabel()
        self._license.setWordWrap(True)
        self._license.setStyleSheet("color: #555;")
        layout.addWidget(self._license)

        self._insight_hint = QLabel()
        self._insight_hint.setWordWrap(True)
        self._insight_hint.setStyleSheet("color: #8a4b08;")
        layout.addWidget(self._insight_hint)

        return page

    def _build_matching_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        hint = QLabel(
            "Higher match threshold = stricter “this is the target person”.\n"
            "Leave thresholds on Auto to use values tuned for the selected model pack."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._auto_thresholds = QCheckBox("Use recommended thresholds for the selected model")
        self._auto_thresholds.toggled.connect(self._on_auto_thresholds_toggled)
        layout.addWidget(self._auto_thresholds)

        self._match_spin = QDoubleSpinBox()
        self._match_spin.setRange(0.05, 0.95)
        self._match_spin.setSingleStep(0.01)
        self._match_spin.setDecimals(3)

        self._low_spin = QDoubleSpinBox()
        self._low_spin.setRange(0.05, 0.95)
        self._low_spin.setSingleStep(0.01)
        self._low_spin.setDecimals(3)

        self._det_size = QSpinBox()
        self._det_size.setRange(320, 1280)
        self._det_size.setSingleStep(64)
        self._det_size.setToolTip(
            "InsightFace only. Larger finds smaller faces but is slower "
            "(640 is a good default)."
        )

        form = QFormLayout()
        form.addRow("Match threshold", self._match_spin)
        form.addRow("Low-confidence threshold", self._low_spin)
        form.addRow("Detection size", self._det_size)
        layout.addLayout(form)

        self._force_reprocess = QCheckBox(
            "After changing models, force a full re-analysis next time"
        )
        layout.addWidget(self._force_reprocess)
        layout.addStretch(1)
        return page

    def _build_downloads_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(
            QLabel(
                "Models are stored under the project’s models/ folder "
                "(and downloaded only when needed)."
            )
        )

        self._status_box = QTextEdit()
        self._status_box.setReadOnly(True)
        layout.addWidget(self._status_box, stretch=1)

        row = QHBoxLayout()
        refresh = QPushButton("Refresh Status")
        refresh.clicked.connect(self._refresh_download_status)
        download = QPushButton("Download Selected Identity Pack…")
        download.clicked.connect(self._download_selected)
        download_age = QPushButton("Download MiVOLO Age Model…")
        download_age.clicked.connect(self._download_mivolo)
        row.addWidget(refresh)
        row.addWidget(download)
        row.addWidget(download_age)
        row.addStretch(1)
        layout.addLayout(row)

        self._refresh_download_status()
        return page

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._privacy_banner = QCheckBox("Show privacy banner on the welcome screen")
        self._verbose = QCheckBox("Verbose logging")
        layout.addWidget(self._privacy_banner)
        layout.addWidget(self._verbose)

        about = QGroupBox("About model licenses")
        about_layout = QVBoxLayout(about)
        about_text = QLabel(
            "• OpenCV Fast — OpenCV Zoo / Apache-friendly ecosystem; fine for personal use.\n"
            "• InsightFace buffalo_* / antelopev2 — pretrained weights are for "
            "non-commercial / personal research use only (code is MIT).\n"
            "• MiVOLO v2 — research age/gender model (personal / research use).\n"
            "This app is intended for personal, non-commercial photo sorting. "
            "Do not use InsightFace packs in a commercial product without a license."
        )
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)
        layout.addWidget(about)
        layout.addStretch(1)
        return page

    def _populate_from_settings(self) -> None:
        settings = self._settings
        index = self._preset_combo.findData(settings.model_preset)
        if index < 0:
            index = self._preset_combo.findData(ModelPresetId.INSIGHTFACE_BUFFALO_L.value)
        self._preset_combo.setCurrentIndex(max(0, index))

        age_index = self._age_combo.findData(settings.age_backend)
        if age_index < 0:
            age_index = self._age_combo.findData(AgeBackendId.BUILTIN.value)
        self._age_combo.setCurrentIndex(max(0, age_index))

        auto = (
            settings.match_threshold is None
            and settings.low_confidence_threshold is None
        )
        self._auto_thresholds.setChecked(auto)
        preset = get_preset(settings.resolved_preset_id())
        self._match_spin.setValue(
            settings.match_threshold
            if settings.match_threshold is not None
            else preset.default_match_threshold
        )
        self._low_spin.setValue(
            settings.low_confidence_threshold
            if settings.low_confidence_threshold is not None
            else preset.default_low_confidence_threshold
        )
        self._on_auto_thresholds_toggled(auto)
        self._det_size.setValue(settings.det_size)
        self._force_reprocess.setChecked(settings.force_reprocess_after_model_change)
        self._privacy_banner.setChecked(settings.show_privacy_banner)
        self._verbose.setChecked(settings.log_verbose)
        self._on_preset_changed()

    def _selected_preset(self) -> ModelPreset:
        value = self._preset_combo.currentData()
        return get_preset(str(value))

    def _selected_age_backend(self) -> AgeBackendInfo:
        value = self._age_combo.currentData()
        return get_age_backend(str(value))

    def _on_age_backend_changed(self) -> None:
        self._on_preset_changed()

    def _on_preset_changed(self) -> None:
        preset = self._selected_preset()
        age = self._selected_age_backend()
        self._badge.setText(
            f"<b>Identity:</b> {preset.short_label} "
            f"(speed {preset.speed}, quality {preset.quality}, "
            f"{preset.download_size})<br>"
            f"<b>Age:</b> {age.short_label} "
            f"({age.download_size}, {age.ram_hint})"
        )
        self._details.setPlainText(
            f"—— Identity pack ——\n{preset.summary}\n\n{preset.details}\n\n"
            f"—— Age model ——\n{age.summary}\n\n{age.details}"
        )
        self._license.setText(
            f"Identity license: {preset.license_note}\n"
            f"Age license: {age.license_note}"
        )

        hints: list[str] = []
        if preset.backend == BackendFamily.INSIGHTFACE and not insightface_available():
            err = insightface_import_error() or "not installed"
            hints.append(
                "The face identity pack needs an extra piece "
                "(InsightFace). Click Save Settings — ChronoFace can install it "
                f"for you.\n({err})"
            )
        if (
            age.id == AgeBackendId.MIVOLO_V2
            and not mivolo_available()
        ):
            hints.append(
                "The better age model needs a few extra pieces "
                "(PyTorch and related tools). Click Save Settings — ChronoFace "
                "can download and install them for you "
                "(needs internet; may take several minutes).\n"
                f"({mivolo_import_error()})"
            )
        self._insight_hint.setText("\n\n".join(hints))

        if self._auto_thresholds.isChecked():
            self._match_spin.setValue(preset.default_match_threshold)
            self._low_spin.setValue(preset.default_low_confidence_threshold)

    def _on_auto_thresholds_toggled(self, checked: bool) -> None:
        self._match_spin.setEnabled(not checked)
        self._low_spin.setEnabled(not checked)
        if checked:
            preset = self._selected_preset()
            self._match_spin.setValue(preset.default_match_threshold)
            self._low_spin.setValue(preset.default_low_confidence_threshold)

    def _refresh_download_status(self) -> None:
        lines = []
        for row in describe_install_status():
            mark = "✓" if row.installed else "○"
            lines.append(f"{mark} {row.title}\n   {row.detail}")
            if row.path is not None:
                lines.append(f"   Path: {row.path}")
            lines.append("")
        self._status_box.setPlainText("\n".join(lines).strip())

    def _download_selected(self) -> None:
        preset = self._selected_preset()
        try:
            ensure_models_for_preset(preset.id.value, download=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Download Failed", str(exc))
            self._refresh_download_status()
            return
        self._refresh_download_status()
        QMessageBox.information(
            self,
            "Models Ready",
            f"Model pack “{preset.title}” is ready to use.",
        )

    def _download_mivolo(self) -> None:
        try:
            ensure_models_for_preset("age_mivolo_v2", download=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Download Failed", str(exc))
            self._refresh_download_status()
            return
        self._refresh_download_status()
        QMessageBox.information(
            self,
            "MiVOLO Ready",
            "MiVOLO v2 age model is downloaded and ready.\n"
            "Select it under Settings → Models → Age model, then re-analyze.",
        )

    def _confirm_install(
        self,
        *,
        title: str,
        text: str,
        informative: str,
    ) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(title)
        box.setText(text)
        box.setInformativeText(informative)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        yes = box.button(QMessageBox.StandardButton.Yes)
        no = box.button(QMessageBox.StandardButton.No)
        if yes is not None:
            yes.setText("Install && Save")
        if no is not None:
            no.setText("Cancel")
        return box.exec() == QMessageBox.StandardButton.Yes

    def _center_on_parent(self, dialog: QWidget) -> None:
        dialog.adjustSize()
        parent = dialog.parentWidget()
        if parent is None:
            return
        parent_rect = parent.frameGeometry()
        dialog_rect = dialog.frameGeometry()
        dialog.move(
            parent_rect.x() + (parent_rect.width() - dialog_rect.width()) // 2,
            parent_rect.y() + (parent_rect.height() - dialog_rect.height()) // 2,
        )

    def _run_install_with_progress(
        self,
        *,
        title: str,
        start_label: str,
        installer,
    ) -> bool:
        progress = QProgressDialog(start_label, None, 0, 0, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setMinimumWidth(420)
        progress.show()
        self._center_on_parent(progress)

        thread = QThread(self)
        worker = _PipInstallWorker(installer)
        worker.moveToThread(thread)

        result = {"ok": False, "error": ""}
        loop = QEventLoop(self)

        def on_progress(message: str) -> None:
            progress.setLabelText(message)
            self._center_on_parent(progress)

        def on_finished() -> None:
            result["ok"] = True
            thread.quit()

        def on_failed(message: str) -> None:
            result["error"] = message
            thread.quit()

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(loop.quit)

        thread.start()
        loop.exec()
        thread.wait(5000)

        progress.close()
        if result["ok"]:
            return True

        QMessageBox.critical(
            self,
            "Install Failed",
            "ChronoFace could not finish installing.\n\n"
            f"{result['error']}",
        )
        return False

    def _ensure_insightface_installed(self) -> bool:
        if insightface_available():
            return True
        if not self._confirm_install(
            title="Extra Piece Needed",
            text=(
                "This face pack needs an extra piece on this computer "
                "(InsightFace)."
            ),
            informative=(
                "ChronoFace can install it for you (needs internet).\n\n"
                "Or choose Identity model pack → OpenCV Fast instead."
            ),
        ):
            return False

        ok = self._run_install_with_progress(
            title="Installing…",
            start_label="Installing face identity support (InsightFace)…",
            installer=lambda on_progress: pip_install(
                ["insightface", "onnx"],
                on_progress=on_progress,
            ),
        )
        if not ok:
            return False
        if not insightface_available():
            QMessageBox.information(
                self,
                "Restart Needed",
                "Install finished. Please close and reopen ChronoFace "
                "so the face pack can load.",
            )
        return True

    def _ensure_mivolo_installed(self) -> bool:
        if mivolo_available():
            return True
        if not self._confirm_install(
            title="Extra Pieces Needed",
            text=(
                "The better age model needs a few extra pieces on this computer "
                "(PyTorch and related tools)."
            ),
            informative=(
                "ChronoFace can download and install them for you.\n"
                "This needs the internet and may take several minutes.\n\n"
                "Or choose Age model → Built-in instead."
            ),
        ):
            return False

        ok = self._run_install_with_progress(
            title="Installing…",
            start_label=(
                "Installing the better age model pieces…\n"
                "This can take several minutes."
            ),
            installer=install_mivolo_dependencies,
        )
        if not ok:
            return False
        if not mivolo_available():
            QMessageBox.information(
                self,
                "Restart Needed",
                "Install finished. Please close and reopen ChronoFace "
                "so the age model can load.",
            )
        else:
            QMessageBox.information(
                self,
                "Ready",
                "The better age model pieces are installed.",
            )
        self._on_preset_changed()
        return True

    def _on_save(self) -> None:
        preset = self._selected_preset()
        age = self._selected_age_backend()
        if (
            preset.backend == BackendFamily.INSIGHTFACE
            and not insightface_available()
        ):
            if not self._ensure_insightface_installed():
                return

        if age.id == AgeBackendId.MIVOLO_V2 and not mivolo_available():
            if not self._ensure_mivolo_installed():
                return

        previous = self._settings.model_preset
        previous_age = self._settings.age_backend
        settings = AppSettings(
            version=self._settings.version,
            model_preset=preset.id.value,
            age_backend=age.id.value,
            match_threshold=(
                None
                if self._auto_thresholds.isChecked()
                else float(self._match_spin.value())
            ),
            low_confidence_threshold=(
                None
                if self._auto_thresholds.isChecked()
                else float(self._low_spin.value())
            ),
            det_size=int(self._det_size.value()),
            force_reprocess_after_model_change=self._force_reprocess.isChecked(),
            last_model_fingerprint=self._settings.last_model_fingerprint,
            show_privacy_banner=self._privacy_banner.isChecked(),
            log_verbose=self._verbose.isChecked(),
        )

        model_changed = (
            previous != settings.model_preset
            or previous_age != settings.age_backend
        )
        if model_changed:
            # Drop the global stamp so the next analyze treats this as a model change
            # even for projects that never had a per-project fingerprint file.
            settings.last_model_fingerprint = ""
            QMessageBox.information(
                self,
                "Model updated",
                "Next Analyze Photos will scan faces again with the new model.",
            )

        save_settings(settings)
        self._result = settings
        self.accept()
