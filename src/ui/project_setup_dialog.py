"""In-app screen for creating or editing a ChronoFace project."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.domain.models import ProjectConfig
from src.ui.reference_selector import ReferenceSelector
from src.ui.message_dialog import MessageDialog


def _default_export_folder(name: str, input_folder: Path) -> Path:
    """Suggested export destination beside the input folder (chosen later at export)."""
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in name).strip()
    safe = "_".join(safe.split()) or "ChronoFace"
    return input_folder.resolve().parent / f"{safe}_export"


class ProjectSetupPage(QWidget):
    """Full-page project create/edit form (not a modal dialog)."""

    saved = Signal(object)  # ProjectConfig
    deleted = Signal()
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectSetupPage")
        self.setStyleSheet("QWidget#projectSetupPage { background: #F7F8FB; }")
        self._existing: ProjectConfig | None = None
        self._result: ProjectConfig | None = None

        self._title = QLabel("New Project")
        self._title.setObjectName("titleLabel")

        self._subtitle = QLabel(
            "Name the project, pick the photo folder, and add reference photos "
            "of the person to track."
        )
        self._subtitle.setObjectName("mutedLabel")
        self._subtitle.setWordWrap(True)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. Maya Bat Mitzvah 2026")

        self._input_edit = QLineEdit()
        self._input_edit.setReadOnly(True)
        input_browse = QPushButton("Browse…")
        input_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        input_browse.clicked.connect(self._browse_input)

        self._include_subfolders = QCheckBox("Include subfolders")
        self._include_subfolders.setChecked(True)
        self._include_subfolders.setToolTip(
            "When checked, photos inside nested folders under the input "
            "folder are scanned too."
        )

        self._dob_enabled = QCheckBox("Date of birth known")
        self._dob_edit = QDateEdit()
        self._dob_edit.setCalendarPopup(True)
        self._dob_edit.setDisplayFormat("yyyy-MM-dd")
        self._dob_edit.setDate(QDate.currentDate().addYears(-13))
        self._dob_edit.setEnabled(False)
        self._dob_enabled.toggled.connect(self._dob_edit.setEnabled)

        self._references = ReferenceSelector()

        privacy = QLabel(
            "All photo analysis is performed locally on this computer. "
            "No photos or facial data are uploaded."
        )
        privacy.setStyleSheet(
            "QLabel {"
            "  background: #ECFDF5; border: 1px solid #A7F3D0;"
            "  border-radius: 10px; padding: 12px 16px;"
            "  color: #065F46; font-weight: 600;"
            "}"
        )
        privacy.setWordWrap(True)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self._input_edit, stretch=1)
        input_row.addWidget(input_browse)

        input_col = QVBoxLayout()
        input_col.setSpacing(6)
        input_col.addLayout(input_row)
        input_col.addWidget(self._include_subfolders)

        dob_row = QHBoxLayout()
        dob_row.addWidget(self._dob_enabled)
        dob_row.addWidget(self._dob_edit, stretch=1)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.addRow("Project name", self._name_edit)
        form.addRow("Input photo folder", input_col)
        form.addRow("Date of birth", dob_row)

        note = QLabel(
            "Original photos are never modified. You will choose an output "
            "folder when you export numbered copies."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)

        ref_heading = QLabel("Reference photos of the target person")
        ref_heading.setObjectName("sectionTitle")

        self._save_button = QPushButton("Create Project")
        self._save_button.setObjectName("primaryButton")
        self._save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_button.clicked.connect(self._on_save)

        cancel_button = QPushButton("Cancel")
        cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_button.clicked.connect(self.cancelled.emit)

        self._delete_button = QPushButton("Delete Project")
        self._delete_button.setObjectName("dangerButton")
        self._delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_button.setToolTip(
            "Permanently remove this project's ChronoFace data. "
            "Original photos are never deleted."
        )
        self._delete_button.clicked.connect(self._on_delete)
        self._delete_button.hide()

        button_row = QHBoxLayout()
        button_row.addWidget(self._delete_button)
        button_row.addStretch(1)
        button_row.addWidget(cancel_button)
        button_row.addWidget(self._save_button)

        card = QFrame()
        card.setObjectName("card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setSpacing(14)
        card_layout.addWidget(self._title)
        card_layout.addWidget(self._subtitle)
        card_layout.addWidget(privacy)
        card_layout.addLayout(form)
        card_layout.addWidget(note)
        card_layout.addSpacing(4)
        card_layout.addWidget(ref_heading)
        card_layout.addWidget(self._references, stretch=1)
        card_layout.addLayout(button_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(card)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.addWidget(scroll)

    def prepare_new(self) -> None:
        """Reset form for creating a project."""
        self._existing = None
        self._result = None
        self._title.setText("New Project")
        self._save_button.setText("Create Project")
        self._delete_button.hide()
        self._name_edit.clear()
        self._input_edit.clear()
        self._include_subfolders.setChecked(True)
        self._dob_enabled.setChecked(False)
        self._dob_edit.setDate(QDate.currentDate().addYears(-13))
        self._references.set_references([])

    def prepare_edit(self, config: ProjectConfig) -> None:
        """Load an existing project for editing."""
        self._existing = config
        self._result = None
        self._title.setText("Edit Project")
        self._save_button.setText("Save Changes")
        self._delete_button.show()
        self._populate(config)

    def project_config(self) -> ProjectConfig | None:
        return self._result

    def _populate(self, config: ProjectConfig) -> None:
        self._name_edit.setText(config.name)
        self._input_edit.setText(str(config.input_folder))
        self._include_subfolders.setChecked(config.include_subfolders)
        if config.date_of_birth is not None:
            self._dob_enabled.setChecked(True)
            self._dob_edit.setDate(
                QDate(
                    config.date_of_birth.year,
                    config.date_of_birth.month,
                    config.date_of_birth.day,
                )
            )
        else:
            self._dob_enabled.setChecked(False)
        self._references.set_references(config.reference_photos)

    def _browse_input(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Input Photo Folder")
        if path:
            self._input_edit.setText(path)

    def _on_delete(self) -> None:
        if self._existing is None:
            return
        name = self._existing.name
        if not MessageDialog.question(
            self,
            "Delete Project",
            f'Delete project "{name}"?',
            informative=(
                "This permanently removes ChronoFace analysis data, cache files, "
                "and project settings for this project.\n\n"
                "Your original photos and reference photo files are not deleted."
            ),
            yes_text="Delete",
            no_text="Cancel",
            dangerous=True,
            default_yes=False,
        ):
            return
        self.deleted.emit()

    def _on_save(self) -> None:
        name = self._name_edit.text().strip()
        input_folder = self._input_edit.text().strip()
        include_subfolders = self._include_subfolders.isChecked()
        references = self._references.references()

        if not name:
            MessageDialog.warning(self, "Missing Name", "Please enter a project name.")
            return
        if not input_folder or not Path(input_folder).is_dir():
            MessageDialog.warning(
                self,
                "Invalid Input Folder",
                "Please select an existing input photo folder.",
            )
            return
        if not references:
            MessageDialog.warning(
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
                MessageDialog.warning(
                    self,
                    "Invalid Date of Birth",
                    "Date of birth cannot be in the future.",
                )
                return

        input_path = Path(input_folder)
        if self._existing is not None:
            output_folder = Path(self._existing.output_folder)
        else:
            output_folder = _default_export_folder(name, input_path)

        if input_path.resolve() == output_folder.resolve():
            output_folder = input_path.resolve().parent / f"{name}_ChronoFace_export"

        if self._existing is not None:
            config = ProjectConfig(
                id=self._existing.id,
                name=name,
                input_folder=input_path,
                output_folder=output_folder,
                date_of_birth=dob,
                reference_photos=references,
                include_subfolders=include_subfolders,
                created_at=self._existing.created_at,
            )
        else:
            config = ProjectConfig(
                name=name,
                input_folder=input_path,
                output_folder=output_folder,
                date_of_birth=dob,
                reference_photos=references,
                include_subfolders=include_subfolders,
            )

        self._result = config
        self.saved.emit(config)


# Back-compat alias.
ProjectSetupDialog = ProjectSetupPage
