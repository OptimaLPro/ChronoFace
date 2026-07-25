"""Export options dialog for numbered age-ordered photo copies."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.export.file_exporter import AgeRangeFolder, ExportOptions
from src.ui.message_dialog import MessageDialog, OverlayDialog
from src.ui import theme as T


class _AgeRangeRow(QWidget):
    """One min–max age band with a remove control."""

    def __init__(self, parent=None, *, min_age: int = 0, max_age: int = 2) -> None:
        super().__init__(parent)
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 120)
        self.min_spin.setValue(min_age)
        self.min_spin.setFixedWidth(64)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(0, 120)
        self.max_spin.setValue(max_age)
        self.max_spin.setFixedWidth(64)

        dash = QLabel("–")
        dash.setStyleSheet(f"color: {T.TEXT_MUTED}; border: none;")
        dash.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setObjectName("ghostButton")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setFixedWidth(72)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.min_spin)
        row.addWidget(dash)
        row.addWidget(self.max_spin)
        row.addStretch(1)
        row.addWidget(self.remove_btn)

    def age_range(self) -> tuple[int, int]:
        return self.min_spin.value(), self.max_spin.value()


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
        self._range_rows: list[_AgeRangeRow] = []

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

        folders_header = QHBoxLayout()
        folders_header.setSpacing(8)
        folders_title = QLabel("Age range folders")
        folders_title.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {T.TEXT}; border: none;"
        )
        add_range = QPushButton("Add")
        add_range.setObjectName("ghostButton")
        add_range.setCursor(Qt.CursorShape.PointingHandCursor)
        add_range.setFixedWidth(64)
        add_range.clicked.connect(self._add_range_row)
        folders_header.addWidget(folders_title)
        folders_header.addStretch(1)
        folders_header.addWidget(add_range)

        folders_hint = QLabel(
            "Optional. Split main photos into subfolders by age "
            "(e.g. 0–2, 3–7, 8–10). Leave empty for a flat export."
        )
        folders_hint.setWordWrap(True)
        folders_hint.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: 12px; border: none;"
        )

        self._ranges_host = QWidget()
        self._ranges_layout = QVBoxLayout(self._ranges_host)
        self._ranges_layout.setContentsMargins(0, 0, 0, 0)
        self._ranges_layout.setSpacing(6)

        self._empty_ranges = QLabel("No age folders — photos export to the output root.")
        self._empty_ranges.setStyleSheet(
            f"color: {T.TEXT_SOFT}; font-size: 12px; border: none;"
        )
        self._ranges_layout.addWidget(self._empty_ranges)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMaximumHeight(140)
        scroll.setWidget(self._ranges_host)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

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
        self._card_layout.addLayout(folders_header)
        self._card_layout.addWidget(folders_hint)
        self._card_layout.addWidget(scroll)
        self._card_layout.addLayout(buttons)
        self._layout_card()

    def export_options(self) -> ExportOptions | None:
        return self._result

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Export Output Folder")
        if path:
            self._output_edit.setText(path)

    def _suggested_next_range(self) -> tuple[int, int]:
        if not self._range_rows:
            return 0, 2
        last_max = max(row.max_spin.value() for row in self._range_rows)
        start = last_max + 1
        return start, min(start + 3, 120)

    def _add_range_row(self) -> None:
        min_age, max_age = self._suggested_next_range()
        row = _AgeRangeRow(self._ranges_host, min_age=min_age, max_age=max_age)
        row.remove_btn.clicked.connect(lambda: self._remove_range_row(row))
        self._range_rows.append(row)
        self._empty_ranges.setVisible(False)
        self._ranges_layout.addWidget(row)
        self._layout_card()

    def _remove_range_row(self, row: _AgeRangeRow) -> None:
        if row not in self._range_rows:
            return
        self._range_rows.remove(row)
        self._ranges_layout.removeWidget(row)
        row.deleteLater()
        self._empty_ranges.setVisible(not self._range_rows)
        self._layout_card()

    def _collect_age_ranges(self) -> list[AgeRangeFolder] | None:
        if not self._range_rows:
            return []

        ranges: list[AgeRangeFolder] = []
        for row in self._range_rows:
            lo, hi = row.age_range()
            if lo > hi:
                MessageDialog.warning(
                    self,
                    "Invalid Age Range",
                    f"Age range {lo}–{hi} is invalid. Min must be ≤ max.",
                )
                return None
            ranges.append(AgeRangeFolder(min_age=lo, max_age=hi))

        ordered = sorted(ranges, key=lambda r: (r.min_age, r.max_age))
        for prev, curr in zip(ordered, ordered[1:]):
            if curr.min_age <= prev.max_age:
                MessageDialog.warning(
                    self,
                    "Overlapping Age Ranges",
                    f"Ranges {prev.folder_name} and {curr.folder_name} overlap. "
                    "Adjust them so each age belongs to one folder.",
                )
                return None
        return ordered

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

        age_ranges = self._collect_age_ranges()
        if age_ranges is None:
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
            age_range_folders=age_ranges,
        )
        self.accept()
