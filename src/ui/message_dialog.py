"""Themed modal dialogs — alerts, confirms, progress, and choice lists."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.icons import icon_pixmap
from src.ui import theme as T


class MessageKind(Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    QUESTION = "question"


_KIND_ICON = {
    MessageKind.INFO: ("alert-circle", T.PRIMARY),
    MessageKind.SUCCESS: ("check-circle", T.SUCCESS),
    MessageKind.WARNING: ("alert-circle", T.WARNING),
    MessageKind.ERROR: ("x-circle", T.ERROR),
    MessageKind.QUESTION: ("alert-circle", T.PRIMARY),
}


class OverlayDialog(QDialog):
    """Frameless dimmed-backdrop shell; card content filled by subclasses."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        min_card_width: int = 380,
        max_card_width: int = 520,
    ) -> None:
        super().__init__(parent)
        self._min_card_width = min_card_width
        self._max_card_width = max_card_width
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._backdrop = QWidget(self)
        self._backdrop.setObjectName("dialogBackdrop")
        self._backdrop.setStyleSheet(
            "#dialogBackdrop { background-color: rgba(15, 23, 42, 140); }"
        )
        self._backdrop.lower()

        self._card = QFrame(self)
        self._card.setObjectName("messageCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card.setStyleSheet(
            "QFrame#messageCard {"
            f"  background: {T.CARD};"
            f"  border: 1px solid {T.BORDER};"
            "  border-radius: 16px;"
            "}"
        )

        self._card_layout = QVBoxLayout(self._card)
        self._card_layout.setContentsMargins(24, 22, 24, 20)
        self._card_layout.setSpacing(14)

        if parent is not None:
            top = parent.window()
            self.setGeometry(top.frameGeometry())
        else:
            self.resize(720, 480)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._backdrop.setGeometry(self.rect())
        self._layout_card()

    def _layout_card(self) -> None:
        max_w = min(self._max_card_width, max(320, self.width() - 48))
        card_w = max(self._min_card_width, min(max_w, self._max_card_width))
        self._card.setFixedWidth(card_w)
        self._card.setMinimumHeight(0)
        self._card.setMaximumHeight(16777215)
        # Word-wrapped labels need heightForWidth; plain sizeHint is often too short.
        self._card_layout.activate()
        if self._card.hasHeightForWidth():
            card_h = self._card.heightForWidth(card_w)
        else:
            card_h = self._card.sizeHint().height()
        card_h = max(card_h, self._card.minimumSizeHint().height())
        max_h = max(200, self.height() - 48)
        if card_h > max_h:
            card_h = max_h
            self._card.setFixedHeight(card_h)
        x = (self.width() - card_w) // 2
        y = max(24, (self.height() - card_h) // 2)
        self._card.setGeometry(x, y, card_w, card_h)
        self._card.raise_()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Clicks on dimmed area do not dismiss — alerts need an explicit choice.
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


class MessageDialog(OverlayDialog):
    """Single-purpose themed alert / confirm card."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        text: str,
        kind: MessageKind = MessageKind.INFO,
        informative: str = "",
        buttons: list[tuple[str, str, object]] | None = None,
        default_role: object = "accept",
    ) -> None:
        """
        buttons: list of (label, objectName, role)
          role is "accept" | "reject" | "destructive" | custom done-code int
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self._clicked_role: object | None = None

        header = QHBoxLayout()
        header.setSpacing(12)

        icon_name, icon_color = _KIND_ICON[kind]
        icon_label = QLabel()
        icon_label.setFixedSize(40, 40)
        icon_label.setPixmap(icon_pixmap(icon_name, size=36, color=icon_color))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("titleLabel")
        title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {T.TEXT}; border: none;"
        )
        title_label.setWordWrap(True)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"font-size: 13px; color: {T.TEXT}; border: none; line-height: 1.4;"
        )
        titles.addWidget(title_label)
        titles.addWidget(body)
        if informative:
            info = QLabel(informative)
            info.setWordWrap(True)
            info.setObjectName("mutedLabel")
            info.setStyleSheet(
                f"font-size: 12px; color: {T.TEXT_MUTED}; border: none;"
                f" background: {T.BACKGROUND}; border-radius: 8px;"
                " padding: 10px 12px;"
            )
            titles.addWidget(info)

        header.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(titles, 1)
        self._card_layout.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)

        if buttons is None:
            buttons = [("OK", "primaryButton", "accept")]

        self._default_btn: QPushButton | None = None
        for label, object_name, role in buttons:
            btn = QPushButton(label)
            if object_name:
                btn.setObjectName(object_name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, r=role: self._on_button(r)
            )
            row.addWidget(btn)
            if role == default_role or (
                self._default_btn is None and role == "accept"
            ):
                self._default_btn = btn
                btn.setDefault(True)

        self._card_layout.addLayout(row)
        self._layout_card()

    def _on_button(self, role: object) -> None:
        self._clicked_role = role
        if role == "reject":
            self.reject()
        elif isinstance(role, int):
            self.done(role)
        else:
            self.accept()

    def clicked_role(self) -> object | None:
        return self._clicked_role

    @staticmethod
    def information(
        parent: QWidget | None,
        title: str,
        text: str,
        informative: str = "",
    ) -> None:
        MessageDialog(
            parent,
            title=title,
            text=text,
            kind=MessageKind.INFO,
            informative=informative,
        ).exec()

    @staticmethod
    def success(
        parent: QWidget | None,
        title: str,
        text: str,
        informative: str = "",
    ) -> None:
        MessageDialog(
            parent,
            title=title,
            text=text,
            kind=MessageKind.SUCCESS,
            informative=informative,
        ).exec()

    @staticmethod
    def warning(
        parent: QWidget | None,
        title: str,
        text: str,
        informative: str = "",
    ) -> None:
        MessageDialog(
            parent,
            title=title,
            text=text,
            kind=MessageKind.WARNING,
            informative=informative,
        ).exec()

    @staticmethod
    def critical(
        parent: QWidget | None,
        title: str,
        text: str,
        informative: str = "",
    ) -> None:
        MessageDialog(
            parent,
            title=title,
            text=text,
            kind=MessageKind.ERROR,
            informative=informative,
        ).exec()

    @staticmethod
    def question(
        parent: QWidget | None,
        title: str,
        text: str,
        *,
        informative: str = "",
        yes_text: str = "Yes",
        no_text: str = "Cancel",
        dangerous: bool = False,
        default_yes: bool = False,
    ) -> bool:
        """Return True when the affirmative button is chosen."""
        yes_style = "dangerButton" if dangerous else "primaryButton"
        default = "accept" if default_yes else "reject"
        dialog = MessageDialog(
            parent,
            title=title,
            text=text,
            kind=MessageKind.QUESTION,
            informative=informative,
            buttons=[
                (no_text, "ghostButton", "reject"),
                (yes_text, yes_style, "accept"),
            ],
            default_role=default,
        )
        return dialog.exec() == QDialog.DialogCode.Accepted

    @staticmethod
    def about(parent: QWidget | None, title: str, text: str) -> None:
        MessageDialog(
            parent,
            title=title,
            text=text,
            kind=MessageKind.INFO,
        ).exec()


class ProgressDialog(OverlayDialog):
    """Themed indeterminate / determinate progress modal."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "Working…",
        label: str = "",
        minimum: int = 0,
        maximum: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {T.TEXT}; border: none;"
        )
        self._label = QLabel(label or "Please wait…")
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            f"font-size: 13px; color: {T.TEXT_MUTED}; border: none;"
        )

        self._bar = QProgressBar()
        self._bar.setTextVisible(maximum > 0)
        self._bar.setRange(minimum, maximum)
        if maximum <= 0:
            self._bar.setRange(0, 0)

        self._card_layout.addWidget(title_label)
        self._card_layout.addWidget(self._label)
        self._card_layout.addWidget(self._bar)
        self._layout_card()

    def setLabelText(self, text: str) -> None:  # noqa: N802 — Qt API mirror
        self._label.setText(text)
        self._layout_card()

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        self._bar.setRange(minimum, maximum)
        self._bar.setTextVisible(maximum > 0)
        self._layout_card()

    def setMaximum(self, maximum: int) -> None:  # noqa: N802
        self._bar.setMaximum(maximum)
        self._bar.setTextVisible(maximum > 0)
        self._layout_card()

    def setMinimum(self, minimum: int) -> None:  # noqa: N802
        self._bar.setMinimum(minimum)

    def setValue(self, value: int) -> None:  # noqa: N802
        self._bar.setValue(value)

    def setMinimumWidth(self, width: int) -> None:  # noqa: N802
        self._card.setMinimumWidth(width)
        self._layout_card()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # Block Esc while work runs (matches cancel-less QProgressDialog).
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)


class ChoiceDialog(OverlayDialog):
    """Themed single-item picker (replaces QInputDialog.getItem)."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        label: str,
        items: list[str],
        current: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._choice: str | None = None

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {T.TEXT}; border: none;"
        )
        prompt = QLabel(label)
        prompt.setStyleSheet(
            f"font-size: 13px; color: {T.TEXT_MUTED}; border: none;"
        )
        self._combo = QComboBox()
        self._combo.addItems(items)
        if 0 <= current < len(items):
            self._combo.setCurrentIndex(current)

        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghostButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)

        ok = QPushButton("Open")
        ok.setObjectName("primaryButton")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self._accept_choice)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)

        self._card_layout.addWidget(title_label)
        self._card_layout.addWidget(prompt)
        self._card_layout.addWidget(self._combo)
        self._card_layout.addLayout(row)
        self._layout_card()

    def _accept_choice(self) -> None:
        self._choice = self._combo.currentText()
        self.accept()

    def choice(self) -> str | None:
        return self._choice

    @staticmethod
    def get_item(
        parent: QWidget | None,
        title: str,
        label: str,
        items: list[str],
        current: int = 0,
    ) -> tuple[str, bool]:
        if not items:
            return "", False
        dialog = ChoiceDialog(
            parent, title=title, label=label, items=items, current=current
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return "", False
        return dialog.choice() or "", True
