"""Processing progress view for metadata / analysis scans."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.domain.models import ScanSummary


class ProcessingView(QWidget):
    """Shows scan progress and supports cancellation."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._status = QLabel("Idle")
        self._status.setWordWrap(True)

        self._progress = QProgressBar()
        self._progress.setMinimum(0)
        self._progress.setMaximum(100)
        self._progress.setValue(0)

        self._detail = QLabel("")
        self._detail.setWordWrap(True)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setUndoRedoEnabled(False)
        self._log.setMinimumHeight(120)

        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.setEnabled(False)
        self._cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_button.setStyleSheet(
            "QPushButton {"
            "  font-weight: 600; padding: 8px 14px;"
            "  background: #c62828; color: #ffffff; border: 1px solid #b71c1c;"
            "  border-radius: 6px;"
            "}"
            "QPushButton:hover { background: #d32f2f; border-color: #c62828; }"
            "QPushButton:pressed { background: #b71c1c; }"
            "QPushButton:disabled {"
            "  color: #b8bec8; background: #f3f4f7; border-color: #e4e7ec;"
            "}"
        )
        self._cancel_button.clicked.connect(self.cancel_requested.emit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Processing"))
        layout.addWidget(self._status)
        layout.addWidget(self._progress)
        layout.addWidget(self._detail)
        layout.addWidget(self._log)
        layout.addLayout(buttons)

    def reset(self) -> None:
        self._status.setText("Idle")
        self._detail.setText("")
        self._progress.setValue(0)
        self._progress.setMaximum(100)
        self._log.clear()
        self._cancel_button.setEnabled(False)

    def start(self, total_hint: int | None = None) -> None:
        self._status.setText("Starting scan…")
        self._detail.setText("")
        self._progress.setValue(0)
        self._progress.setMaximum(max(total_hint or 0, 1))
        self._log.clear()
        self._cancel_button.setEnabled(True)
        self.append_log("Metadata scan started (local only).")

    def update_progress(self, current: int, total: int, message: str) -> None:
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(min(current, total))
        self._status.setText(f"Processing photo {current} of {total}")
        self._detail.setText(message)

    def append_log(self, message: str) -> None:
        self._log.append(message)

    def finish_success(self, summary: ScanSummary) -> None:
        self._cancel_button.setEnabled(False)
        self._progress.setValue(self._progress.maximum())
        self._status.setText("Scan complete")
        self._detail.setText(self._format_summary(summary))
        self.append_log(self._format_summary(summary))

    def finish_success_message(self, message: str) -> None:
        self._cancel_button.setEnabled(False)
        self._progress.setValue(self._progress.maximum())
        self._status.setText("Export complete")
        self._detail.setText(message)
        self.append_log(message)

    def finish_cancelled(self) -> None:
        self._cancel_button.setEnabled(False)
        self._status.setText("Scan cancelled")
        self.append_log("Scan cancelled. Partial progress was saved.")

    def finish_error(self, message: str) -> None:
        self._cancel_button.setEnabled(False)
        self._status.setText("Scan failed")
        self._detail.setText(message)
        self.append_log(f"Error: {message}")

    @staticmethod
    def _format_summary(summary: ScanSummary) -> str:
        lines = [
            f"Discovered {summary.total_discovered} images. "
            f"Processed {summary.processed}, "
            f"skipped unchanged {summary.skipped_unchanged}, "
            f"errors {summary.errors}.",
            f"Dates — reliable EXIF: {summary.with_reliable_date}, "
            f"weak filesystem: {summary.with_weak_date}, "
            f"none: {summary.with_no_date}.",
        ]
        if summary.reference_embeddings or summary.faces_processed:
            lines.append(
                f"Faces — references: {summary.reference_embeddings}, "
                f"analyzed: {summary.faces_processed}, "
                f"target found: {summary.target_found}, "
                f"not found: {summary.target_not_found}, "
                f"no face: {summary.no_face}, "
                f"low confidence: {summary.low_confidence}."
            )
        return "\n".join(lines)
