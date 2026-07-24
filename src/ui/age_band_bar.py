"""Colored horizontal age-range indicator for the chronological timeline."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from src.ui.theme import AGE_BAND_COLORS


class AgeBandBar(QWidget):
    """Segmented age line: 0–2 … 26+."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(40)

        labels = QHBoxLayout()
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(0)

        segments = QHBoxLayout()
        segments.setContentsMargins(0, 0, 0, 0)
        segments.setSpacing(2)

        for index, (label, color) in enumerate(AGE_BAND_COLORS):
            text = QLabel(label)
            text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text.setStyleSheet(
                "color: #6B7280; font-size: 11px; font-weight: 600; background: transparent;"
            )
            labels.addWidget(text, stretch=1)

            seg = QLabel()
            seg.setFixedHeight(8)
            left_radius = "8px" if index == 0 else "2px"
            right_radius = "8px" if index == len(AGE_BAND_COLORS) - 1 else "2px"
            seg.setStyleSheet(
                f"background: {color}; border-top-left-radius: {left_radius};"
                f" border-bottom-left-radius: {left_radius};"
                f" border-top-right-radius: {right_radius};"
                f" border-bottom-right-radius: {right_radius};"
            )
            segments.addWidget(seg, stretch=1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(labels)
        layout.addLayout(segments)
