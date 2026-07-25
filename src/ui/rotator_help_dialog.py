"""First-run instructions for Rotator mode (animated key + photo demo)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.message_dialog import OverlayDialog
from src.ui import theme as T


class _RotatorDemoAnim(QWidget):
    """Two-frame loop: sideways photo + keys → finger presses R → upright photo."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame = 0
        self.setMinimumHeight(168)
        self.setMaximumHeight(180)
        self._timer = QTimer(self)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._frame = 1 - self._frame
        self.update()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        if not self._timer.isActive():
            self._timer.start()
        super().showEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Soft stage background
        stage = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(T.BACKGROUND))
        painter.drawRoundedRect(stage.adjusted(0, 0, -1, -1), 12, 12)

        # --- Photo preview (left) ---
        photo_box = QRectF(20, 28, 100, 100)
        painter.setBrush(QColor("#0F172A"))
        painter.setPen(QPen(QColor(T.BORDER), 1.5))
        painter.drawRoundedRect(photo_box, 10, 10)

        # Fake portrait content: upright = tall blue bar; wrong = sideways
        painter.setPen(Qt.PenStyle.NoPen)
        if self._frame == 0:
            # Sideways "person" (wrong)
            painter.setBrush(QColor("#93C5FD"))
            painter.drawRoundedRect(QRectF(34, 62, 72, 32), 8, 8)
            painter.setBrush(QColor("#FDE68A"))
            painter.drawEllipse(QRectF(40, 68, 20, 20))
        else:
            # Upright after rotate
            painter.setBrush(QColor("#93C5FD"))
            painter.drawRoundedRect(QRectF(52, 40, 36, 72), 8, 8)
            painter.setBrush(QColor("#FDE68A"))
            painter.drawEllipse(QRectF(58, 46, 24, 24))

        caption = "Before" if self._frame == 0 else "After"
        painter.setPen(QColor(T.TEXT_MUTED))
        font = QFont(painter.font())
        font.setPointSize(9)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(20, 132, 100, 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            caption,
        )

        # Arrow between photo and keys
        painter.setPen(QPen(QColor(T.PRIMARY), 2.2))
        ax = 138
        ay = 78
        painter.drawLine(ax, ay, ax + 28, ay)
        painter.drawLine(ax + 28, ay, ax + 20, ay - 6)
        painter.drawLine(ax + 28, ay, ax + 20, ay + 6)

        # --- Keyboard keys E / R ---
        key_y = 48
        e_rect = QRectF(180, key_y, 52, 52)
        r_rect = QRectF(242, key_y, 52, 52)
        self._draw_key(
            painter,
            e_rect,
            "E",
            "Left",
            pressed=False,
        )
        self._draw_key(
            painter,
            r_rect,
            "R",
            "Right",
            pressed=self._frame == 1,
        )

        # Finger cue over R
        finger_x = r_rect.center().x()
        if self._frame == 0:
            finger_y = r_rect.bottom() + 18
            tip_y = r_rect.bottom() + 4
        else:
            finger_y = r_rect.bottom() + 6
            tip_y = r_rect.center().y() + 10

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FBBF24"))
        # fingertip
        painter.drawEllipse(QRectF(finger_x - 9, tip_y - 9, 18, 18))
        # finger body
        path = QPainterPath()
        path.moveTo(finger_x - 7, tip_y)
        path.lineTo(finger_x - 10, finger_y + 22)
        path.lineTo(finger_x + 10, finger_y + 22)
        path.lineTo(finger_x + 7, tip_y)
        path.closeSubpath()
        painter.drawPath(path)

        painter.setPen(QColor(T.TEXT_SOFT))
        font.setPointSize(8)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        hint = "Press R → rotate right" if self._frame == 0 else "Photo fixed ✓"
        painter.drawText(
            QRectF(170, 132, 140, 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            hint,
        )

    def _draw_key(
        self,
        painter: QPainter,
        rect: QRectF,
        letter: str,
        subtitle: str,
        *,
        pressed: bool,
    ) -> None:
        bg = QColor(T.PRIMARY) if pressed else QColor(T.CARD)
        border = QColor(T.PRIMARY) if pressed else QColor(T.BORDER)
        fg = QColor("#FFFFFF") if pressed else QColor(T.TEXT)
        y_off = 2 if pressed else 0
        body = rect.adjusted(0, y_off, 0, y_off)

        # Drop shadow when not pressed
        if not pressed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(15, 23, 42, 28))
            painter.drawRoundedRect(rect.adjusted(0, 3, 0, 3), 10, 10)

        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.5))
        painter.drawRoundedRect(body, 10, 10)

        painter.setPen(fg)
        font = QFont(painter.font())
        font.setPointSize(16)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(body.adjusted(0, -6, 0, 0), Qt.AlignmentFlag.AlignCenter, letter)

        painter.setPen(QColor("#FFFFFF") if pressed else QColor(T.TEXT_MUTED))
        font.setPointSize(8)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            body.adjusted(0, 18, 0, 0),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            subtitle,
        )


class RotatorHelpDialog(OverlayDialog):
    """Explain E/R keys and how to exit Rotator mode."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, min_card_width=420, max_card_width=480)
        self.setWindowTitle("Photo Rotator")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._never_again = False

        title = QLabel("Photo Rotator")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {T.TEXT}; border: none;"
        )
        subtitle = QLabel(
            "Fix sideways photos without losing quality. "
            "Select a photo, then use the keys below."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: 13px; border: none;"
        )

        self._demo = _RotatorDemoAnim()

        keys = QLabel(
            "<b>E</b> — rotate left &nbsp;&nbsp;·&nbsp;&nbsp; "
            "<b>R</b> — rotate right<br/>"
            "Click <b>Rotator</b> again when you are done."
        )
        keys.setWordWrap(True)
        keys.setTextFormat(Qt.TextFormat.RichText)
        keys.setStyleSheet(
            f"color: {T.TEXT}; background: {T.BACKGROUND}; border: 1px solid {T.BORDER};"
            " border-radius: 10px; padding: 12px 14px; font-size: 13px;"
        )

        note = QLabel(
            "Rotations are lossless: JPEG uses DCT block transforms "
            "(same approach as JPEG Lossless Rotator). PNG and WebP stay lossless too."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {T.TEXT_SOFT}; font-size: 12px; border: none;"
        )

        self._never_check = QCheckBox("Never show this again")
        self._never_check.setCursor(Qt.CursorShape.PointingHandCursor)

        got_it = QPushButton("Got it")
        got_it.setObjectName("primaryButton")
        got_it.setCursor(Qt.CursorShape.PointingHandCursor)
        got_it.setDefault(True)
        got_it.clicked.connect(self._accept)

        actions = QHBoxLayout()
        actions.addWidget(self._never_check)
        actions.addStretch(1)
        actions.addWidget(got_it)

        self._card_layout.addWidget(title)
        self._card_layout.addWidget(subtitle)
        self._card_layout.addWidget(self._demo)
        self._card_layout.addWidget(keys)
        self._card_layout.addWidget(note)
        self._card_layout.addLayout(actions)

    @property
    def never_show_again(self) -> bool:
        return self._never_again

    def _accept(self) -> None:
        self._never_again = self._never_check.isChecked()
        self.accept()
