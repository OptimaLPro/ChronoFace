"""Bottom processing status bar — visible only while busy or briefly after."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.domain.models import ScanSummary
from src.ui.icons import icon_pixmap

_SUCCESS_AUTO_HIDE_MS = 4500


class ProcessingStatusBar(QWidget):
    """
    Footer progress that stays out of the way when idle.

    - Hidden when idle
    - Shown with Cancel while a job runs
    - On success: brief confirmation, then auto-hides (Dismiss available)
    - On error/cancel: stays until Dismiss
    """

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(56)
        self._busy = False

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        frame = QFrame()
        frame.setObjectName("card")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._frame = frame

        self._icon = QLabel()
        self._icon.setFixedSize(20, 20)

        self._status = QLabel("")
        self._status.setStyleSheet("font-weight: 600;")

        self._detail = QLabel("")
        self._detail.setObjectName("mutedLabel")
        self._detail.setWordWrap(True)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("%v / %m photos processed")

        self._cancel = QPushButton("Cancel")
        self._cancel.setObjectName("dangerButton")
        self._cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel.clicked.connect(self.cancel_requested.emit)

        self._dismiss = QPushButton("Dismiss")
        self._dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismiss.clicked.connect(self.hide)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        top.addWidget(self._icon)
        top.addWidget(self._status)
        top.addWidget(self._detail, stretch=1)
        top.addWidget(self._cancel)
        top.addWidget(self._dismiss)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self._progress)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        self.reset()

    def reset(self) -> None:
        self._busy = False
        self._hide_timer.stop()
        self._status.setText("")
        self._detail.setText("")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("")
        self._progress.hide()
        self._cancel.hide()
        self._dismiss.hide()
        self._set_icon("#6B7280")
        self._frame.setStyleSheet("")
        self.hide()

    def start(self, total_hint: int | None = None) -> None:
        self._busy = True
        self._hide_timer.stop()
        self.show()
        self._set_icon("#2F6BFF")
        self._status.setText("Processing…")
        self._detail.setText("Starting")
        maximum = max(total_hint or 0, 1)
        self._progress.show()
        self._progress.setObjectName("")
        self._progress.style().unpolish(self._progress)
        self._progress.style().polish(self._progress)
        self._progress.setRange(0, maximum)
        self._progress.setValue(0)
        self._progress.setFormat("%v / %m photos processed")
        self._cancel.show()
        self._cancel.setEnabled(True)
        self._dismiss.hide()
        self._frame.setStyleSheet("")

    def update_progress(self, current: int, total: int, message: str) -> None:
        if not self.isVisible():
            self.show()
        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(min(current, total))
        self._status.setText("Processing…")
        self._detail.setText(message)

    def append_log(self, message: str) -> None:
        self._detail.setText(message)

    def finish_success(self, summary: ScanSummary) -> None:
        self._busy = False
        self._cancel.hide()
        self._cancel.setEnabled(False)
        self._dismiss.show()
        self._set_icon("#16A34A")
        self._progress.show()
        self._progress.setObjectName("successBar")
        self._progress.style().unpolish(self._progress)
        self._progress.style().polish(self._progress)
        self._progress.setValue(self._progress.maximum())
        self._status.setText("Processing complete")
        self._detail.setText(
            f"{summary.processed} processed · "
            f"{summary.target_found} target found · "
            f"{summary.low_confidence} low confidence"
        )
        self._frame.setStyleSheet(
            "QFrame#card {"
            "  background: #ECFDF5;"
            "  border: 1px solid #A7F3D0;"
            "  border-radius: 12px;"
            "}"
        )
        self.show()
        self._hide_timer.start(_SUCCESS_AUTO_HIDE_MS)

    def finish_success_message(self, message: str) -> None:
        self._busy = False
        self._cancel.hide()
        self._cancel.setEnabled(False)
        self._dismiss.show()
        self._set_icon("#16A34A")
        self._progress.show()
        self._progress.setObjectName("successBar")
        self._progress.style().unpolish(self._progress)
        self._progress.style().polish(self._progress)
        self._progress.setValue(self._progress.maximum())
        self._status.setText("Complete")
        self._detail.setText(message)
        self._progress.setFormat("Done")
        self._frame.setStyleSheet(
            "QFrame#card {"
            "  background: #ECFDF5;"
            "  border: 1px solid #A7F3D0;"
            "  border-radius: 12px;"
            "}"
        )
        self.show()
        self._hide_timer.start(_SUCCESS_AUTO_HIDE_MS)

    def finish_cancelled(self) -> None:
        self._busy = False
        self._cancel.hide()
        self._cancel.setEnabled(False)
        self._dismiss.show()
        self._set_icon("#D97706")
        self._status.setText("Cancelled")
        self._detail.setText("Partial progress was saved.")
        self._progress.hide()
        self._frame.setStyleSheet(
            "QFrame#card {"
            "  background: #FFFBEB;"
            "  border: 1px solid #FDE68A;"
            "  border-radius: 12px;"
            "}"
        )
        self.show()

    def finish_error(self, message: str) -> None:
        self._busy = False
        self._cancel.hide()
        self._cancel.setEnabled(False)
        self._dismiss.show()
        self._set_icon("#DC2626")
        self._status.setText("Failed")
        self._detail.setText(message)
        self._progress.hide()
        self._frame.setStyleSheet(
            "QFrame#card {"
            "  background: #FEF2F2;"
            "  border: 1px solid #FECACA;"
            "  border-radius: 12px;"
            "}"
        )
        self.show()

    def _set_icon(self, color: str) -> None:
        self._icon.setPixmap(icon_pixmap("check-circle", size=18, color=color))
