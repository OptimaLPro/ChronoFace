"""Application Settings page — models, matching, downloads."""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
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
from src.ui.message_dialog import MessageDialog, ProgressDialog


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


class SettingsPage(QWidget):
    """Let the user pick model packs and matching thresholds."""

    settings_saved = Signal(object)  # AppSettings
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.setStyleSheet("QWidget#settingsPage { background: #F7F8FB; }")

        self._settings = load_settings()
        self._result: AppSettings | None = None
        self._nav_buttons: list[QPushButton] = []

        title = QLabel("Settings")
        title.setObjectName("titleLabel")
        subtitle = QLabel(
            "Choose local models, matching thresholds, and downloads. "
            "Nothing leaves this computer."
        )
        subtitle.setObjectName("mutedLabel")
        subtitle.setWordWrap(True)

        self._stack = QStackedWidget()
        sections = (
            ("Models", self._build_models_tab()),
            ("Matching", self._build_matching_tab()),
            ("Downloads", self._build_downloads_tab()),
            ("General", self._build_general_tab()),
        )
        nav_frame = QFrame()
        nav_frame.setObjectName("settingsNav")
        nav_frame.setStyleSheet(
            "QFrame#settingsNav {"
            "  background: #FFFFFF; border: 1px solid #E5E7EB;"
            "  border-radius: 10px;"
            "}"
        )
        nav = QHBoxLayout(nav_frame)
        nav.setContentsMargins(4, 4, 4, 4)
        nav.setSpacing(4)
        for index, (label, page) in enumerate(sections):
            self._stack.addWidget(page)
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(index == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton {"
                "  font-weight: 600; padding: 8px 18px; border: none;"
                "  background: transparent; color: #6B7280; border-radius: 8px;"
                "}"
                "QPushButton:hover { background: #F3F4F6; color: #1F2937; }"
                "QPushButton:checked {"
                "  background: #2F6BFF; color: #FFFFFF;"
                "}"
            )
            btn.clicked.connect(
                lambda checked=False, i=index: self._show_section(i)
            )
            self._nav_buttons.append(btn)
            nav.addWidget(btn)
        nav.addStretch(1)

        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("primaryButton")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self._on_cancel)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)

        card = QFrame()
        card.setObjectName("card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(16)
        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addWidget(nav_frame)
        card_layout.addWidget(self._stack, stretch=1)
        card_layout.addLayout(buttons)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(card)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(0)
        layout.addWidget(scroll)

        self._populate_from_settings()

    def _show_section(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)

    @staticmethod
    def _section_card(
        *widgets: QWidget,
        stretch_last: bool = False,
    ) -> QWidget:
        """Wrap section body widgets in a light nested panel."""
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)
        last = len(widgets) - 1
        for index, widget in enumerate(widgets):
            if stretch_last and index == last:
                layout.addWidget(widget, stretch=1)
            else:
                layout.addWidget(widget)
        if not stretch_last:
            layout.addStretch(1)
        return inner

    @staticmethod
    def _info_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("mutedLabel")
        return label

    @staticmethod
    def _styled_text() -> QTextEdit:
        box = QTextEdit()
        box.setReadOnly(True)
        box.setStyleSheet(
            "QTextEdit {"
            "  background: #F9FAFB; border: 1px solid #EEF0F4;"
            "  border-radius: 10px; padding: 12px; color: #374151;"
            "}"
        )
        return box

    def reload(self) -> None:
        """Reload persisted settings into the form (e.g. when showing the page)."""
        self._settings = load_settings()
        self._result = None
        self._populate_from_settings()

    def saved_settings(self) -> AppSettings | None:
        return self._result

    def _on_cancel(self) -> None:
        self.reload()
        self.cancelled.emit()

    def _build_models_tab(self) -> QWidget:
        intro = self._info_label(
            "Choose a local model pack. Everything runs on this computer — nothing "
            "is uploaded. InsightFace packs are among the best open-source face "
            "models for personal / non-commercial use."
        )

        self._preset_combo = QComboBox()
        for preset in list_presets():
            label = preset.title
            if preset.recommended:
                label += "  · recommended"
            self._preset_combo.addItem(label, preset.id.value)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        self._age_combo = QComboBox()
        for backend in list_age_backends():
            label = backend.title
            if backend.recommended:
                label += "  · recommended for age"
            self._age_combo.addItem(label, backend.id.value)
        self._age_combo.currentIndexChanged.connect(self._on_age_backend_changed)

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.addRow("Identity model pack", self._preset_combo)
        form.addRow("Age model", self._age_combo)

        self._badge = QLabel()
        self._badge.setWordWrap(True)
        self._badge.setStyleSheet(
            "QLabel {"
            "  background: #EEF2FF; border: 1px solid #C7D2FE;"
            "  padding: 12px 14px; border-radius: 10px; color: #1E3A8A;"
            "}"
        )

        self._details = self._styled_text()
        self._details.setMinimumHeight(200)

        self._license = QLabel()
        self._license.setWordWrap(True)
        self._license.setObjectName("mutedLabel")

        self._insight_hint = QLabel()
        self._insight_hint.setWordWrap(True)
        self._insight_hint.setStyleSheet(
            "QLabel {"
            "  background: #FFFBEB; border: 1px solid #FDE68A;"
            "  padding: 12px 14px; border-radius: 10px; color: #92400E;"
            "}"
        )

        # Pack details as stretch target via host so license/hints stay below.
        details_host = QWidget()
        details_layout = QVBoxLayout(details_host)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(12)
        details_layout.addWidget(self._details, stretch=1)
        details_layout.addWidget(self._license)
        details_layout.addWidget(self._insight_hint)

        return self._section_card(
            intro, form_host, self._badge, details_host, stretch_last=True
        )

    def _build_matching_tab(self) -> QWidget:
        hint = self._info_label(
            "Higher match threshold = stricter “this is the target person”. "
            "Leave thresholds on Auto to use values tuned for the selected model pack."
        )

        self._auto_thresholds = QCheckBox(
            "Use recommended thresholds for the selected model"
        )
        self._auto_thresholds.toggled.connect(self._on_auto_thresholds_toggled)

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

        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.addRow("Match threshold", self._match_spin)
        form.addRow("Low-confidence threshold", self._low_spin)
        form.addRow("Detection size", self._det_size)

        self._force_reprocess = QCheckBox(
            "After changing models, force a full re-analysis next time"
        )
        return self._section_card(
            hint, self._auto_thresholds, form_host, self._force_reprocess
        )

    def _build_downloads_tab(self) -> QWidget:
        intro = self._info_label(
            "Models are stored under the project’s models/ folder "
            "and downloaded only when needed."
        )

        self._status_box = self._styled_text()

        refresh = QPushButton("Refresh Status")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self._refresh_download_status)
        download = QPushButton("Download Selected Identity Pack…")
        download.setObjectName("primaryButton")
        download.setCursor(Qt.CursorShape.PointingHandCursor)
        download.clicked.connect(self._download_selected)
        download_age = QPushButton("Download MiVOLO Age Model…")
        download_age.setCursor(Qt.CursorShape.PointingHandCursor)
        download_age.clicked.connect(self._download_mivolo)

        row_host = QWidget()
        row = QHBoxLayout(row_host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(refresh)
        row.addWidget(download)
        row.addWidget(download_age)
        row.addStretch(1)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(intro)
        layout.addWidget(self._status_box, stretch=1)
        layout.addWidget(row_host)
        self._refresh_download_status()
        return page

    def _build_general_tab(self) -> QWidget:
        self._privacy_banner = QCheckBox("Show privacy banner on the welcome screen")
        self._verbose = QCheckBox("Verbose logging")

        about_title = QLabel("About model licenses")
        about_title.setObjectName("sectionTitle")
        about_text = QLabel(
            "• OpenCV Fast — OpenCV Zoo / Apache-friendly ecosystem; fine for personal use.\n"
            "• InsightFace buffalo_* / antelopev2 — pretrained weights are for "
            "non-commercial / personal research use only (code is MIT).\n"
            "• MiVOLO v2 — research age/gender model (personal / research use).\n"
            "This app is intended for personal, non-commercial photo sorting. "
            "Do not use InsightFace packs in a commercial product without a license."
        )
        about_text.setWordWrap(True)
        about_text.setStyleSheet(
            "QLabel {"
            "  background: #F9FAFB; border: 1px solid #EEF0F4;"
            "  border-radius: 10px; padding: 14px; color: #374151;"
            "}"
        )
        return self._section_card(
            self._privacy_banner, self._verbose, about_title, about_text
        )

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
        hint_text = "\n\n".join(hints)
        self._insight_hint.setText(hint_text)
        self._insight_hint.setVisible(bool(hint_text.strip()))

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
            MessageDialog.critical(self, "Download Failed", str(exc))
            self._refresh_download_status()
            return
        self._refresh_download_status()
        MessageDialog.information(
            self,
            "Models Ready",
            f"Model pack “{preset.title}” is ready to use.",
        )

    def _download_mivolo(self) -> None:
        try:
            ensure_models_for_preset("age_mivolo_v2", download=True)
        except Exception as exc:  # noqa: BLE001
            MessageDialog.critical(self, "Download Failed", str(exc))
            self._refresh_download_status()
            return
        self._refresh_download_status()
        MessageDialog.information(
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
        return MessageDialog.question(
            self,
            title,
            text,
            informative=informative,
            yes_text="Install and Save",
            no_text="Cancel",
            default_yes=True,
        )

    def _run_install_with_progress(
        self,
        *,
        title: str,
        start_label: str,
        installer,
    ) -> bool:
        progress = ProgressDialog(
            self, title=title, label=start_label, minimum=0, maximum=0
        )
        progress.setMinimumWidth(420)
        progress.show()

        thread = QThread(self)
        worker = _PipInstallWorker(installer)
        worker.moveToThread(thread)

        result = {"ok": False, "error": ""}
        loop = QEventLoop(self)

        def on_progress(message: str) -> None:
            progress.setLabelText(message)

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

        MessageDialog.critical(
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
            MessageDialog.information(
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
            MessageDialog.information(
                self,
                "Restart Needed",
                "Install finished. Please close and reopen ChronoFace "
                "so the age model can load.",
            )
        else:
            MessageDialog.information(
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
            MessageDialog.information(
                self,
                "Model updated",
                "Next Analyze Photos will scan faces again with the new model.",
            )

        save_settings(settings)
        self._result = settings
        self._settings = settings
        self.settings_saved.emit(settings)


# Back-compat alias for imports that still use the old name.
SettingsDialog = SettingsPage
