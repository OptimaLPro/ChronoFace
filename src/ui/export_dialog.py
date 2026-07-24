"""Export options dialog for numbered age-ordered photo copies."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from src.export.file_exporter import ExportOptions
from src.ui.message_dialog import MessageDialog, OverlayDialog
from src.ui import theme as T


class ExportDialog(OverlayDialog):
    """Collect export destination and options."""

    def __init__(
        self,
        parent=None,
        *,
        default_output: Path | None = None,
        matched_count: int = 0,
        unresolved_count: int = 0,
        excluded_count: int = 0,
    ) -> None:
        super().__init__(parent, min_card_width=480, max_card_width=560)
        self.setWindowTitle("Export Numbered Photos")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._result: ExportOptions | None = None

        title = QLabel("Export numbered photos")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {T.TEXT}; border: none;"
        )
        subtitle = QLabel(
            "Copy sorted photos into a folder. Originals are never modified."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: 13px; border: none;"
        )

        summary = QLabel(
            f"Matched / main: {matched_count}  ·  "
            f"Unresolved: {unresolved_count}  ·  "
            f"Excluded: {excluded_count}"
        )
        summary.setWordWrap(True)
        summary.setStyleSheet(
            f"color: {T.TEXT}; background: {T.BACKGROUND}; border: 1px solid {T.BORDER};"
            " border-radius: 10px; padding: 10px 12px; font-size: 13px;"
        )

        self._output_edit = QLineEdit(str(default_output or ""))
        browse = QPushButton("Browse…")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse)

        output_row = QHBoxLayout()
        output_row.setSpacing(8)
        output_row.addWidget(self._output_edit, stretch=1)
        output_row.addWidget(browse)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Output folder", output_row)

        self._include_age = QCheckBox(
            "Include age in filename (0001_age_07_name.jpg)"
        )
        self._include_age.setChecked(True)

        self._only_matched = QCheckBox(
            "Main folder: only photos where the target person was found"
        )
        self._only_matched.setChecked(True)

        self._unresolved = QCheckBox(
            "Also export unresolved / low-confidence photos to _unresolved"
        )
        self._unresolved.setChecked(True)

        self._excluded = QCheckBox(
            "Also export no-face / no-match photos to _excluded"
        )
        self._excluded.setChecked(True)

        self._csv = QCheckBox("Write CSV report (export_report.csv)")
        self._csv.setChecked(True)

        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghostButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)

        export_btn = QPushButton("Export")
        export_btn.setObjectName("primaryButton")
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.setDefault(True)
        export_btn.clicked.connect(self._on_accept)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(export_btn)

        self._card_layout.addWidget(title)
        self._card_layout.addWidget(subtitle)
        self._card_layout.addWidget(summary)
        self._card_layout.addLayout(form)
        for box in (
            self._include_age,
            self._only_matched,
            self._unresolved,
            self._excluded,
            self._csv,
        ):
            self._card_layout.addWidget(box)
        self._card_layout.addLayout(buttons)
        self._layout_card()

    def export_options(self) -> ExportOptions | None:
        return self._result

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Export Output Folder")
        if path:
            self._output_edit.setText(path)

    def _on_accept(self) -> None:
        raw = self._output_edit.text().strip()
        if not raw:
            MessageDialog.warning(self, "Missing Folder", "Choose an output folder.")
            return
        output = Path(raw)
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            MessageDialog.critical(
                self,
                "Output Folder Error",
                f"Could not create or access the output folder:\n{exc}",
            )
            return

        self._result = ExportOptions(
            output_dir=output,
            include_age_in_name=self._include_age.isChecked(),
            export_matched=True,
            export_all_in_main=not self._only_matched.isChecked(),
            export_unresolved_separate=self._unresolved.isChecked(),
            export_excluded_separate=self._excluded.isChecked(),
            write_csv=self._csv.isChecked(),
            only_target_found=self._only_matched.isChecked(),
        )
        self.accept()
