"""Equal-width metric summary cards."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
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
    """White card with icon, large number, and label. Clickable filter control."""

    clicked = Signal()

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
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", False)

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

    def set_selected(self, selected: bool) -> None:
        if bool(self.property("selected")) == selected:
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MetricsRow(QWidget):
    """Row of five project metric cards that drive the timeline filter."""

    filter_requested = Signal(str)  # ReviewFilter value

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

        self._cards: dict[str, MetricCard] = {
            "all": self._scanned,
            "target_found": self._found,
            "needs_review": self._review,
            "not_found": self._not_found,
            "with_exif": self._dates,
        }
        for key, card in self._cards.items():
            card.clicked.connect(lambda k=key: self._on_card_clicked(k))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for card in self._cards.values():
            layout.addWidget(card, stretch=1)

        self.set_active_filter("all")

    def _on_card_clicked(self, key: str) -> None:
        self.set_active_filter(key)
        self.filter_requested.emit(key)

    def set_active_filter(self, key: str) -> None:
        """Highlight the card that matches the timeline filter (or none)."""
        for card_key, card in self._cards.items():
            card.set_selected(card_key == key)

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
