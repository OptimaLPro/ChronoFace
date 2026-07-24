"""Dimmed-backdrop photo lightbox for the review workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QWidget

from src.ui.thumbnail_loader import load_thumbnail_pixmap

_CLOSE_BUTTON_STYLE = (
    "QPushButton {"
    "  color: #ef4444;"
    "  font-weight: 800;"
    "  font-size: 28px;"
    "  background: transparent;"
    "  border: none;"
    "  padding: 4px 10px;"
    "}"
    "QPushButton:hover { color: #dc2626; }"
    "QPushButton:pressed { color: #b91c1c; }"
)


class PhotoLightboxDialog(QDialog):
    """Show a photo centered on a dim backdrop; click backdrop or press Esc to close."""

    def __init__(
        self,
        image_path: Path | str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._image_path = Path(image_path)
        self._source = QPixmap()
        self.setModal(True)
        self.setWindowTitle("Photo")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._backdrop = QWidget(self)
        self._backdrop.setObjectName("lightboxBackdrop")
        self._backdrop.setStyleSheet(
            "#lightboxBackdrop { background-color: rgba(0, 0, 0, 210); }"
        )
        self._backdrop.setCursor(Qt.CursorShape.PointingHandCursor)
        self._backdrop.lower()

        self._close_btn = QPushButton("✕", self)
        self._close_btn.setObjectName("lightboxClose")
        self._close_btn.setToolTip("Close")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setStyleSheet(_CLOSE_BUTTON_STYLE)
        self._close_btn.setFlat(True)
        self._close_btn.clicked.connect(self.accept)
        self._close_btn.raise_()

        self._image = QLabel(self)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setStyleSheet(
            "QLabel {"
            "  background: #111;"
            "  border: 1px solid #666;"
            "}"
        )
        self._image.setCursor(Qt.CursorShape.ArrowCursor)

        self._hint = QLabel("Click outside the photo or press Esc to close", self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet(
            "QLabel { color: #ddd; background: transparent; padding: 4px; }"
        )
        self._hint.setCursor(Qt.CursorShape.PointingHandCursor)

        if parent is not None:
            top = parent.window()
            self.setGeometry(top.frameGeometry())
        else:
            self.resize(960, 720)

        self._source = load_thumbnail_pixmap(self._image_path, size=1600)
        if self._source.isNull():
            self._image.setText("Could not load photo")
            self._image.setStyleSheet(
                "QLabel { color: #eee; background: #222; padding: 24px; }"
            )
        else:
            self._fit_image()
        self._layout_chrome()

    def _layout_chrome(self) -> None:
        """Place the close control in the top-left corner of the modal."""
        btn_w = max(44, self._close_btn.sizeHint().width())
        btn_h = max(40, self._close_btn.sizeHint().height())
        self._close_btn.setGeometry(12, 8, btn_w, btn_h)
        self._close_btn.raise_()

    def _fit_image(self) -> None:
        pad_x = 96
        pad_y = 120
        available = self.size()
        target_w = max(120, available.width() - pad_x)
        target_h = max(120, available.height() - pad_y)

        if self._source.isNull():
            self._image.adjustSize()
            pix_w = max(240, self._image.sizeHint().width())
            pix_h = max(80, self._image.sizeHint().height())
        else:
            scaled = self._source.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._image.setPixmap(scaled)
            pix_w = scaled.width()
            pix_h = scaled.height()

        x = (available.width() - pix_w) // 2
        y = max(24, (available.height() - pix_h - 36) // 2)
        self._image.setGeometry(x, y, pix_w, pix_h)

        hint_h = self._hint.sizeHint().height()
        self._hint.setGeometry(
            24,
            min(available.height() - hint_h - 16, y + pix_h + 12),
            available.width() - 48,
            hint_h,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._backdrop.setGeometry(self.rect())
        self._fit_image()
        self._layout_chrome()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if self._close_btn.geometry().contains(pos):
                super().mousePressEvent(event)
                return
            if not self._image.geometry().contains(pos):
                self.accept()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)


def open_photo_lightbox(
    parent: QWidget | None,
    image_path: Path | str | None,
) -> None:
    """Open the lightbox when a readable image path is available."""
    if image_path is None:
        return
    path = Path(image_path)
    if not path.is_file():
        return
    dialog = PhotoLightboxDialog(path, parent)
    dialog.exec()
