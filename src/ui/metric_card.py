"""Equal-width metric summary cards."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.ui.icons import icon_pixmap


class MetricCard(QFrame):
    """White card with icon, large number, and label."""

    def __init__(
        self,
        label: str,
        *,
        icon_name: str,
        icon_color: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(88)

        icon = QLabel()
        icon.setPixmap(icon_pixmap(icon_name, size=22, color=icon_color))
        icon.setFixedSize(28, 28)

        self._value = QLabel("0")
        self._value.setObjectName("metricValue")

        self._label = QLabel(label)
        self._label.setObjectName("metricLabel")

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self._value)
        top.addStretch(1)
        top.addWidget(icon)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        layout.addLayout(top)
        layout.addWidget(self._label)

    def set_value(self, value: int | str) -> None:
        self._value.setText(str(value))


class MetricsRow(QWidget):
    """Row of five project metric cards."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scanned = MetricCard(
            "Photos scanned", icon_name="images", icon_color="#2F6BFF"
        )
        self._found = MetricCard(
            "Target found", icon_name="check-circle", icon_color="#16A34A"
        )
        self._review = MetricCard(
            "Needs review", icon_name="alert-circle", icon_color="#D97706"
        )
        self._not_found = MetricCard(
            "Not found", icon_name="x-circle", icon_color="#DC2626"
        )
        self._dates = MetricCard(
            "With EXIF dates", icon_name="calendar", icon_color="#7C3AED"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for card in (
            self._scanned,
            self._found,
            self._review,
            self._not_found,
            self._dates,
        ):
            layout.addWidget(card, stretch=1)

    def update_stats(self, stats: dict[str, int]) -> None:
        self._scanned.set_value(stats.get("total", 0))
        self._found.set_value(stats.get("target_found", 0))
        if "needs_review_total" in stats:
            needs = stats["needs_review_total"]
        else:
            needs = (
                stats.get("needs_review", 0)
                + stats.get("low_confidence", 0)
                + stats.get("no_face", 0)
            )
        self._review.set_value(needs)
        self._not_found.set_value(stats.get("target_not_found", 0))
        # EXIF-only by default; dashboard passes with_dates explicitly.
        with_dates = stats.get("with_dates", stats.get("reliable_date", 0))
        self._dates.set_value(with_dates)
