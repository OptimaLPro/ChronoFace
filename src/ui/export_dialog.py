"""Export options dialog for numbered Premiere-friendly copies."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.export.file_exporter import ExportOptions


class ExportDialog(QDialog):
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
        super().__init__(parent)
        self.setWindowTitle("Export Numbered Photos")
        self.setMinimumSize(520, 380)
        self.resize(620, 440)
        self.setSizeGripEnabled(True)
        self._result: ExportOptions | None = None

        self._output_edit = QLineEdit(str(default_output or ""))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)

        output_row = QHBoxLayout()
        output_row.addWidget(self._output_edit, stretch=1)
        output_row.addWidget(browse)

        summary = QLabel(
            f"Ready to export sorted copies.\n"
            f"Matched / main: {matched_count}  |  "
            f"Unresolved: {unresolved_count}  |  "
            f"Excluded (no face / no match): {excluded_count}\n\n"
            "Original photos are never modified."
        )
        summary.setWordWrap(True)

        self._include_age = QCheckBox("Include age in filename (0001_age_07_name.jpg)")
        self._include_age.setChecked(True)

        self._only_matched = QCheckBox("Main folder: only photos where the target person was found")
        self._only_matched.setChecked(True)

        self._unresolved = QCheckBox("Also export unresolved / low-confidence photos to _unresolved")
        self._unresolved.setChecked(True)

        self._excluded = QCheckBox("Also export no-face / no-match photos to _excluded")
        self._excluded.setChecked(True)

        self._csv = QCheckBox("Write CSV report (export_report.csv)")
        self._csv.setChecked(True)

        form = QFormLayout()
        form.addRow("Output folder", output_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addLayout(form)
        layout.addWidget(self._include_age)
        layout.addWidget(self._only_matched)
        layout.addWidget(self._unresolved)
        layout.addWidget(self._excluded)
        layout.addWidget(self._csv)
        layout.addWidget(buttons)

    def export_options(self) -> ExportOptions | None:
        return self._result

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Export Output Folder")
        if path:
            self._output_edit.setText(path)

    def _on_accept(self) -> None:
        raw = self._output_edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "Missing Folder", "Choose an output folder.")
            return
        output = Path(raw)
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(
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
