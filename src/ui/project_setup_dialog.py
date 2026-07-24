"""Dialog for creating or editing a ChronoFace project."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
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
    QWidget,
)

from src.domain.models import ProjectConfig
from src.ui.reference_selector import ReferenceSelector

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
_PRIMARY_BUTTON_STYLE = (
    "QPushButton {"
    "  font-weight: 600; padding: 8px 16px;"
    "  background: #2f6fed; color: white; border: none; border-radius: 6px;"
    "}"
    "QPushButton:hover { background: #2558c7; }"
    "QPushButton:pressed { background: #1e4aa8; }"
    "QPushButton:disabled {"
    "  color: #9aa1ab; background: #e8eaee; border: 1px solid #d5d8de;"
    "}"
)


class ProjectSetupDialog(QDialog):
    """Collect project name, folders, optional DOB, and reference photos."""

    def __init__(
        self,
        parent: QWidget | None = None,
        existing: ProjectConfig | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project" if existing is None else "Edit Project")
        self.setMinimumSize(600, 520)
        self.resize(760, 660)
        self.setSizeGripEnabled(True)
        self._existing = existing
        self._result: ProjectConfig | None = None

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. Maya Bat Mitzvah 2026")

        self._input_edit = QLineEdit()
        self._input_edit.setReadOnly(True)
        input_browse = QPushButton("Browse…")
        input_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        input_browse.setStyleSheet(_BUTTON_STYLE)
        input_browse.clicked.connect(self._browse_input)

        self._include_subfolders = QCheckBox("Include subfolders")
        self._include_subfolders.setChecked(True)
        self._include_subfolders.setToolTip(
            "When checked, photos inside nested folders under the input "
            "folder are scanned too."
        )

        self._output_edit = QLineEdit()
        self._output_edit.setReadOnly(True)
        output_browse = QPushButton("Browse…")
        output_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        output_browse.setStyleSheet(_BUTTON_STYLE)
        output_browse.clicked.connect(self._browse_output)

        self._dob_enabled = QCheckBox("Date of birth known")
        self._dob_edit = QDateEdit()
        self._dob_edit.setCalendarPopup(True)
        self._dob_edit.setDisplayFormat("yyyy-MM-dd")
        self._dob_edit.setDate(QDate.currentDate().addYears(-13))
        self._dob_edit.setEnabled(False)
        self._dob_enabled.toggled.connect(self._dob_edit.setEnabled)

        self._references = ReferenceSelector(button_style=_BUTTON_STYLE)

        privacy = QLabel(
            "All photo analysis is performed locally on this computer.\n"
            "No photos or facial data are uploaded."
        )
        privacy.setStyleSheet(
            "QLabel { background: #eef6ee; border: 1px solid #b7d7b7; "
            "border-radius: 6px; padding: 10px 12px; color: #1f4d1f; "
            "font-weight: 600; }"
        )
        privacy.setWordWrap(True)

        input_row = QHBoxLayout()
        input_row.addWidget(self._input_edit, stretch=1)
        input_row.addWidget(input_browse)

        input_col = QVBoxLayout()
        input_col.setSpacing(6)
        input_col.addLayout(input_row)
        input_col.addWidget(self._include_subfolders)

        output_row = QHBoxLayout()
        output_row.addWidget(self._output_edit, stretch=1)
        output_row.addWidget(output_browse)

        dob_row = QHBoxLayout()
        dob_row.addWidget(self._dob_enabled)
        dob_row.addWidget(self._dob_edit, stretch=1)

        form = QFormLayout()
        form.addRow("Project name", self._name_edit)
        form.addRow("Input photo folder", input_col)
        form.addRow("Output folder", output_row)
        form.addRow("Date of birth", dob_row)

        note = QLabel(
            "Original photos are never modified. Exports will be written as "
            "numbered copies into the output folder."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setText(
            "Create Project" if existing is None else "Save Changes"
        )
        save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        save_button.setStyleSheet(_PRIMARY_BUTTON_STYLE)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.setStyleSheet(_BUTTON_STYLE)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(privacy)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(QLabel("Reference photos of the target person"))
        layout.addWidget(self._references, stretch=1)
        layout.addWidget(buttons)

        if existing is not None:
            self._populate(existing)

    def project_config(self) -> ProjectConfig | None:
        """Return the validated config after a successful accept."""
        return self._result

    def _populate(self, config: ProjectConfig) -> None:
        self._name_edit.setText(config.name)
        self._input_edit.setText(str(config.input_folder))
        self._include_subfolders.setChecked(config.include_subfolders)
        self._output_edit.setText(str(config.output_folder))
        if config.date_of_birth is not None:
            self._dob_enabled.setChecked(True)
            self._dob_edit.setDate(
                QDate(
                    config.date_of_birth.year,
                    config.date_of_birth.month,
                    config.date_of_birth.day,
                )
            )
        self._references.set_references(config.reference_photos)

    def _browse_input(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Input Photo Folder")
        if path:
            self._input_edit.setText(path)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            self._output_edit.setText(path)

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        input_folder = self._input_edit.text().strip()
        output_folder = self._output_edit.text().strip()
        include_subfolders = self._include_subfolders.isChecked()
        references = self._references.references()

        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a project name.")
            return
        if not input_folder or not Path(input_folder).is_dir():
            QMessageBox.warning(
                self,
                "Invalid Input Folder",
                "Please select an existing input photo folder.",
            )
            return
        if not output_folder:
            QMessageBox.warning(
                self,
                "Missing Output Folder",
                "Please select an output folder for exported copies.",
            )
            return
        if Path(input_folder).resolve() == Path(output_folder).resolve():
            QMessageBox.warning(
                self,
                "Folders Must Differ",
                "The output folder must be different from the input folder "
                "so original photos are never overwritten.",
            )
            return
        if not references:
            QMessageBox.warning(
                self,
                "Reference Photos Required",
                "Select at least one reference photo of the target person.",
            )
            return

        dob: date | None = None
        if self._dob_enabled.isChecked():
            qdate = self._dob_edit.date()
            dob = date(qdate.year(), qdate.month(), qdate.day())
            if dob > date.today():
                QMessageBox.warning(
                    self,
                    "Invalid Date of Birth",
                    "Date of birth cannot be in the future.",
                )
                return

        try:
            Path(output_folder).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Output Folder Error",
                f"Could not create or access the output folder:\n{exc}",
            )
            return

        if self._existing is not None:
            config = ProjectConfig(
                id=self._existing.id,
                name=name,
                input_folder=Path(input_folder),
                output_folder=Path(output_folder),
                date_of_birth=dob,
                reference_photos=references,
                include_subfolders=include_subfolders,
                created_at=self._existing.created_at,
            )
        else:
            config = ProjectConfig(
                name=name,
                input_folder=Path(input_folder),
                output_folder=Path(output_folder),
                date_of_birth=dob,
                reference_photos=references,
                include_subfolders=include_subfolders,
            )

        self._result = config
        self.accept()
