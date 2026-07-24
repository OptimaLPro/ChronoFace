"""Friendly summary dialog shown after Analyze Photos finishes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.domain.models import ScanSummary
from src.ui.icons import icon_pixmap
from src.ui.message_dialog import OverlayDialog
from src.ui import theme as T


class AnalysisCompleteDialog(OverlayDialog):
    """Scannable analysis summary with a clear next-step action."""

    Review = 1001

    def __init__(self, summary: ScanSummary, parent: QWidget | None = None) -> None:
        super().__init__(parent, min_card_width=440, max_card_width=520)
        self.setWindowTitle("Analysis Complete")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setPixmap(icon_pixmap("check-circle", size=36, color=T.SUCCESS))
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel("Analysis complete")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {T.TEXT}; border: none;"
        )
        hero = QLabel(self._hero_text(summary))
        hero.setWordWrap(True)
        hero.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {T.SUCCESS}; border: none;"
        )
        titles.addWidget(title)
        titles.addWidget(hero)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(titles, 1)

        subtitle = QLabel(self._subtitle_text(summary))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: 12px; border: none;"
        )

        tip = QLabel(
            "Photos are ranked youngest → oldest.\n"
            "Review matches to fix mistakes, then export to a folder."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(
            f"color: {T.TEXT}; background: {T.BACKGROUND}; border: 1px solid {T.BORDER};"
            " border-radius: 10px; padding: 12px 14px; font-size: 12px;"
        )

        close_btn = QPushButton("Close")
        close_btn.setObjectName("ghostButton")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)

        review_btn = QPushButton("Review Results")
        review_btn.setObjectName("primaryButton")
        review_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        review_btn.setDefault(True)
        review_btn.clicked.connect(lambda: self.done(self.Review))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        buttons.addWidget(review_btn)

        self._card_layout.addLayout(header)
        self._card_layout.addWidget(subtitle)
        self._card_layout.addWidget(self._section("Photos", self._photo_rows(summary)))
        self._card_layout.addWidget(self._section("Dates", self._date_rows(summary)))
        if summary.reference_embeddings or summary.faces_processed:
            self._card_layout.addWidget(
                self._section("Faces", self._face_rows(summary))
            )
        self._card_layout.addWidget(tip)
        self._card_layout.addLayout(buttons)
        self._layout_card()

    @staticmethod
    def _hero_text(summary: ScanSummary) -> str:
        if summary.faces_processed or summary.reference_embeddings:
            return (
                f"{summary.target_found} of {summary.faces_processed} photos "
                "matched the person"
            )
        return f"{summary.processed} photos processed"

    @staticmethod
    def _subtitle_text(summary: ScanSummary) -> str:
        parts = [f"{summary.total_discovered} discovered"]
        if summary.skipped_unchanged:
            parts.append(f"{summary.skipped_unchanged} unchanged skipped")
        if summary.errors:
            parts.append(f"{summary.errors} errors")
        else:
            parts.append("no errors")
        return " · ".join(parts)

    @staticmethod
    def _photo_rows(summary: ScanSummary) -> list[tuple[str, str, str | None]]:
        error_color = T.ERROR if summary.errors else None
        return [
            ("Processed", str(summary.processed), None),
            ("Unchanged skipped", str(summary.skipped_unchanged), None),
            ("Errors", str(summary.errors), error_color),
        ]

    @staticmethod
    def _date_rows(summary: ScanSummary) -> list[tuple[str, str, str | None]]:
        return [
            ("Reliable EXIF", str(summary.with_reliable_date), None),
            ("Weak filesystem", str(summary.with_weak_date), None),
            ("No date", str(summary.with_no_date), None),
        ]

    @staticmethod
    def _face_rows(summary: ScanSummary) -> list[tuple[str, str, str | None]]:
        return [
            ("References", str(summary.reference_embeddings), None),
            ("Target found", str(summary.target_found), T.SUCCESS),
            ("Not found", str(summary.target_not_found), None),
            ("Low confidence", str(summary.low_confidence), None),
            ("No face", str(summary.no_face), None),
        ]

    def _section(
        self, title: str, rows: list[tuple[str, str, str | None]]
    ) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {T.BACKGROUND}; border: 1px solid {T.BORDER};"
            " border-radius: 10px; }"
        )
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(6)

        heading = QLabel(title)
        heading.setStyleSheet(
            f"font-weight: 700; font-size: 12px; color: {T.TEXT_MUTED};"
            " border: none; letter-spacing: 0.04em;"
        )
        outer.addWidget(heading)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 1)
        for row_index, (label, value, color) in enumerate(rows):
            name = QLabel(label)
            name.setStyleSheet(f"color: {T.TEXT}; border: none;")
            amount = QLabel(value)
            amount.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            amount.setStyleSheet(
                f"font-weight: 600; border: none; color: {color or T.TEXT};"
            )
            grid.addWidget(name, row_index, 0)
            grid.addWidget(amount, row_index, 1)
        outer.addLayout(grid)
        return frame
