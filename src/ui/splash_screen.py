"""Animated startup splash shown while ChronoFace boots."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Property,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.ui import theme as T
from src.utils.paths import app_icon_png

_STATUS_MESSAGES = (
    "Warming up the workspace…",
    "Loading your projects…",
    "Preparing the photo tools…",
    "Almost ready…",
)

# Keep the splash visible briefly so the motion reads even on fast boots.
_MIN_VISIBLE_MS = 850


class _ChronoMark(QWidget):
    """Pulsing logo with orbiting chrono rings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(168, 168)
        self._phase = 0.0
        self._logo = QPixmap()
        icon_path = app_icon_png()
        if icon_path.is_file():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                self._logo = pixmap.scaled(
                    72,
                    72,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.018) % (math.tau)
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2

        # Soft ambient glow
        glow = QRadialGradient(QPointF(cx, cy), 78)
        glow.setColorAt(0.0, QColor(47, 107, 255, 55))
        glow.setColorAt(0.55, QColor(47, 107, 255, 18))
        glow.setColorAt(1.0, QColor(47, 107, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), 78, 78)

        pulse = 0.5 + 0.5 * math.sin(self._phase * 2)
        badge_r = 40 + pulse * 2.5
        badge = QRadialGradient(QPointF(cx - 8, cy - 10), badge_r * 1.4)
        badge.setColorAt(0.0, QColor("#4C82FF"))
        badge.setColorAt(1.0, QColor(T.PRIMARY))
        painter.setBrush(badge)
        painter.drawEllipse(QPointF(cx, cy), badge_r, badge_r)

        # Outer chrono arcs
        for index, (radius, width, speed, alpha) in enumerate(
            (
                (62.0, 2.4, 1.0, 160),
                (72.0, 1.8, -0.7, 100),
            )
        ):
            pen = QPen(QColor(47, 107, 255, alpha))
            pen.setWidthF(width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            start = int(math.degrees(self._phase * speed) * 16)
            span = int((110 + index * 40) * 16)
            painter.drawArc(rect, start, span)
            painter.drawArc(rect, start + 180 * 16, span)

        # Orbiting dots
        for i, (radius, size, offset) in enumerate(
            ((62.0, 5.0, 0.0), (72.0, 3.5, 1.8), (62.0, 3.0, 3.4))
        ):
            angle = self._phase * (1.15 if i != 1 else -0.85) + offset
            x = cx + math.cos(angle) * radius
            y = cy + math.sin(angle) * radius
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(47, 107, 255, 210 if i == 0 else 140))
            painter.drawEllipse(QPointF(x, y), size, size)

        if not self._logo.isNull():
            logo_x = int(cx - self._logo.width() / 2)
            logo_y = int(cy - self._logo.height() / 2)
            painter.drawPixmap(logo_x, logo_y, self._logo)
        else:
            painter.setPen(QPen(QColor("#FFFFFF"), 2.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(cx, cy - 8), 12, 12)
            path = QPainterPath()
            path.moveTo(cx - 18, cy + 22)
            path.quadTo(cx, cy + 6, cx + 18, cy + 22)
            painter.drawPath(path)


class _ShimmerBar(QWidget):
    """Indeterminate progress bar with a traveling highlight."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self.setMinimumWidth(220)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.02) % 1.0
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#E5E7EB"))
        painter.drawRoundedRect(track, 3, 3)

        span = max(48.0, self.width() * 0.34)
        travel = (self.width() + span) * self._phase - span
        highlight = QRectF(travel, 0, span, self.height())
        grad = QLinearGradient(highlight.topLeft(), highlight.topRight())
        grad.setColorAt(0.0, QColor(47, 107, 255, 0))
        grad.setColorAt(0.45, QColor(47, 107, 255, 220))
        grad.setColorAt(1.0, QColor(47, 107, 255, 0))
        painter.setBrush(grad)
        painter.setClipPath(_rounded_clip(track, 3))
        painter.drawRect(highlight)


def _rounded_clip(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class StartupSplash(QWidget):
    """Frameless boot screen with motion, status copy, and fade-out exit."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("startupSplash")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.SplashScreen
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(420, 460)

        self._opacity = 1.0
        self._fade: QPropertyAnimation | None = None
        self._status_index = 0
        self._pending_window: QWidget | None = None
        self._shown_at = time.monotonic()
        self._finish_timer: QTimer | None = None

        self._mark = _ChronoMark()
        self._shimmer = _ShimmerBar()

        brand = QLabel("ChronoFace")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_font = QFont()
        brand_font.setFamilies(["Segoe UI Variable", "Segoe UI", "Inter"])
        brand_font.setPointSize(22)
        brand_font.setWeight(QFont.Weight.DemiBold)
        brand.setFont(brand_font)
        brand.setStyleSheet(f"color: {T.TEXT}; background: transparent;")

        tagline = QLabel("Sort photos by a person's age")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setStyleSheet(
            f"color: {T.TEXT_MUTED}; background: transparent; font-size: 13px;"
        )

        self._status = QLabel(_STATUS_MESSAGES[0])
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(
            f"color: {T.PRIMARY}; background: transparent;"
            " font-size: 12px; font-weight: 600;"
        )

        card = QWidget()
        card.setObjectName("splashCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 40, 36, 36)
        card_layout.setSpacing(0)
        card_layout.addStretch(1)
        card_layout.addWidget(self._mark, alignment=Qt.AlignmentFlag.AlignHCenter)
        card_layout.addSpacing(22)
        card_layout.addWidget(brand)
        card_layout.addSpacing(6)
        card_layout.addWidget(tagline)
        card_layout.addSpacing(28)
        card_layout.addWidget(self._shimmer)
        card_layout.addSpacing(14)
        card_layout.addWidget(self._status)
        card_layout.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(card)

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1600)
        self._status_timer.timeout.connect(self._advance_status)
        self._status_timer.start()

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float) -> None:
        self._opacity = value
        self._effect.setOpacity(value)

    opacity = Property(float, get_opacity, set_opacity)

    def set_status(self, text: str) -> None:
        """Replace the cycling status with a specific boot step."""
        self._status_timer.stop()
        self._status.setText(text)

    def _advance_status(self) -> None:
        self._status_index = (self._status_index + 1) % len(_STATUS_MESSAGES)
        self._status.setText(_STATUS_MESSAGES[self._status_index])

    def center_on_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(
            geo.center().x() - self.width() // 2,
            geo.center().y() - self.height() // 2,
        )

    def finish_with(self, window: QWidget) -> None:
        """Show the main window, then fade the splash away."""
        self._pending_window = window
        elapsed_ms = (time.monotonic() - self._shown_at) * 1000
        delay = max(0, int(_MIN_VISIBLE_MS - elapsed_ms))
        if delay:
            self._finish_timer = QTimer(self)
            self._finish_timer.setSingleShot(True)
            self._finish_timer.timeout.connect(self._begin_finish)
            self._finish_timer.start(delay)
        else:
            self._begin_finish()

    def _begin_finish(self) -> None:
        window = self._pending_window
        if window is None:
            self.close()
            return

        self._mark.stop()
        self._shimmer.stop()
        self._status_timer.stop()
        self.set_status("Ready")
        window.show()
        window.raise_()
        window.activateWindow()

        self._fade = QPropertyAnimation(self, b"opacity", self)
        self._fade.setDuration(320)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._on_fade_done)
        self._fade.start()

    def _on_fade_done(self) -> None:
        self.close()
        self.deleteLater()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Soft drop shadow
        shadow = QRectF(18, 22, self.width() - 36, self.height() - 34)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(15, 23, 42, 28))
        painter.drawRoundedRect(shadow, 24, 24)

        card = QRectF(12, 12, self.width() - 24, self.height() - 28)
        fill = QLinearGradient(card.topLeft(), card.bottomRight())
        fill.setColorAt(0.0, QColor("#FFFFFF"))
        fill.setColorAt(0.55, QColor("#F7F8FB"))
        fill.setColorAt(1.0, QColor("#EEF3FF"))
        painter.setBrush(fill)
        painter.setPen(QPen(QColor(T.BORDER), 1))
        painter.drawRoundedRect(card, 22, 22)

        # Top accent hairline
        accent = QLinearGradient(card.left() + 40, 0, card.right() - 40, 0)
        accent.setColorAt(0.0, QColor(47, 107, 255, 0))
        accent.setColorAt(0.5, QColor(47, 107, 255, 180))
        accent.setColorAt(1.0, QColor(47, 107, 255, 0))
        painter.setPen(QPen(accent, 2.2))
        y = card.top() + 18
        painter.drawLine(QPointF(card.left() + 48, y), QPointF(card.right() - 48, y))
