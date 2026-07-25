"""Dialog shown after a duplicate scan — summary + one-click remove."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.domain.models import PhotoRecord
from src.sorting.duplicates import DuplicateGroup, DuplicateScanResult
from src.ui.icons import icon_pixmap
from src.ui.message_dialog import MessageDialog, OverlayDialog
from src.ui.photo_lightbox import open_photo_lightbox
from src.ui.thumbnail_loader import load_thumbnail_pixmap
from src.ui import theme as T

_THUMB = 72
_THUMB_RADIUS = 8
_THUMB_COL = 84  # fixed column width so rows align regardless of labels
_PAIR_WIDTH = _THUMB_COL * 2 + 28  # keep + arrow + remove


def _rounded_rect_pixmap(
    source: QPixmap,
    width: int,
    height: int,
    radius: int = _THUMB_RADIUS,
) -> QPixmap:
    result = QPixmap(width, height)
    result.fill(Qt.GlobalColor.transparent)
    if source.isNull():
        return result
    scaled = source.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - width) // 2)
    y = max(0, (scaled.height() - height) // 2)
    cropped = scaled.copy(x, y, width, height)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, width, height, radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, cropped)
    painter.end()
    return result


def _preview_path(photo: PhotoRecord) -> Path | None:
    if photo.original_path.is_file():
        return photo.original_path
    if photo.thumbnail_path is not None and photo.thumbnail_path.is_file():
        return photo.thumbnail_path
    return None


class _ClickableThumb(QLabel):
    """Small photo thumb; click opens the shared lightbox preview."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._clickable = False
        self.setFixedSize(_THUMB, _THUMB)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._base_style = (
            "QLabel {"
            f"  background: {T.CARD};"
            f"  border: 1px solid {T.BORDER};"
            "  border-radius: 8px;"
            "}"
        )
        self.setStyleSheet(self._base_style)

    def set_photo(self, photo: PhotoRecord) -> None:
        source = load_thumbnail_pixmap(
            photo.thumbnail_path or photo.original_path,
            size=_THUMB,
        )
        if source.isNull():
            self.clear()
            self.setText("?")
            self.setStyleSheet(
                self._base_style
                + f"QLabel {{ color: {T.TEXT_MUTED}; font-size: 14px; font-weight: 700; }}"
            )
        else:
            self.setText("")
            self.setPixmap(_rounded_rect_pixmap(source, _THUMB, _THUMB))
            self.setStyleSheet(self._base_style)

        can_preview = _preview_path(photo) is not None
        self._clickable = can_preview
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if can_preview
            else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip(
            f"Click to preview — {photo.original_path.name}"
            if can_preview
            else photo.original_path.name
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._clickable
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _DuplicateGroupRow(QFrame):
    """One duplicate group: fixed thumb columns, names on the right, swap."""

    preview_requested = Signal(object)  # PhotoRecord

    def __init__(
        self,
        group: DuplicateGroup,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._members: list[PhotoRecord] = [group.keeper, *group.duplicates]
        self._keeper_index = 0
        self.setStyleSheet(
            "QFrame {"
            f"  background: {T.BACKGROUND};"
            f"  border: 1px solid {T.BORDER};"
            "  border-radius: 10px;"
            "}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(14)

        # Fixed-width thumb pair so every row aligns the same.
        pair = QWidget()
        pair.setFixedWidth(_PAIR_WIDTH)
        pair_layout = QHBoxLayout(pair)
        pair_layout.setContentsMargins(0, 0, 0, 0)
        pair_layout.setSpacing(8)

        self._keep_thumb = _ClickableThumb()
        self._keep_thumb.clicked.connect(self._preview_keeper)
        self._remove_thumb = _ClickableThumb()
        self._remove_thumb.clicked.connect(self._preview_first_remove)

        keep_col = self._thumb_column(self._keep_thumb, "Keep", T.SUCCESS)
        remove_col = self._thumb_column(self._remove_thumb, "Remove", T.ERROR)

        arrow = QLabel("→")
        arrow.setFixedWidth(20)
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {T.TEXT_MUTED}; border: none;"
        )

        pair_layout.addWidget(keep_col, 0, Qt.AlignmentFlag.AlignTop)
        pair_layout.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)
        pair_layout.addWidget(remove_col, 0, Qt.AlignmentFlag.AlignTop)

        # Names fill the blank right area.
        names_wrap = QWidget()
        names_layout = QVBoxLayout(names_wrap)
        names_layout.setContentsMargins(0, 2, 0, 2)
        names_layout.setSpacing(6)

        self._keep_name = QLabel()
        self._keep_name.setWordWrap(True)
        self._keep_name.setStyleSheet(
            f"font-size: 12px; color: {T.TEXT}; border: none;"
        )
        self._remove_name = QLabel()
        self._remove_name.setWordWrap(True)
        self._remove_name.setStyleSheet(
            f"font-size: 12px; color: {T.TEXT_MUTED}; border: none;"
        )
        names_layout.addWidget(self._keep_name)
        names_layout.addWidget(self._remove_name)
        names_layout.addStretch(1)

        self._swap_btn = QPushButton("Swap")
        self._swap_btn.setObjectName("ghostButton")
        self._swap_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swap_btn.setToolTip("Swap which copy to keep and which to remove")
        self._swap_btn.setFixedWidth(72)
        self._swap_btn.clicked.connect(self.swap)

        root.addWidget(pair, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(names_wrap, 1)
        root.addWidget(self._swap_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._refresh()

    @staticmethod
    def _thumb_column(thumb: _ClickableThumb, role: str, color: str) -> QWidget:
        col = QWidget()
        col.setFixedWidth(_THUMB_COL)
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        badge = QLabel(role)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"QLabel {{ color: {color}; font-size: 10px; font-weight: 700; border: none; }}"
        )
        layout.addWidget(thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(badge)
        return col

    @property
    def keeper(self) -> PhotoRecord:
        return self._members[self._keeper_index]

    @property
    def duplicates(self) -> list[PhotoRecord]:
        return [
            photo
            for index, photo in enumerate(self._members)
            if index != self._keeper_index
        ]

    def swap(self) -> None:
        """Promote the first remove to keep (reverse for pairs)."""
        if len(self._members) < 2:
            return
        # Cycle keeper forward through members.
        self._keeper_index = (self._keeper_index + 1) % len(self._members)
        self._refresh()

    def _refresh(self) -> None:
        keeper = self.keeper
        removes = self.duplicates
        first_remove = removes[0]

        self._keep_thumb.set_photo(keeper)
        self._remove_thumb.set_photo(first_remove)

        self._keep_name.setText(f"Keep: {keeper.original_path.name}")
        if len(removes) == 1:
            self._remove_name.setText(f"Remove: {first_remove.original_path.name}")
        else:
            names = ", ".join(photo.original_path.name for photo in removes)
            self._remove_name.setText(f"Remove ({len(removes)}): {names}")

        self._swap_btn.setEnabled(len(self._members) >= 2)

    def _preview_keeper(self) -> None:
        self.preview_requested.emit(self.keeper)

    def _preview_first_remove(self) -> None:
        removes = self.duplicates
        if removes:
            self.preview_requested.emit(removes[0])


class DuplicatesDialog(OverlayDialog):
    """Present exact-duplicate groups and offer soft-removal of copies."""

    Remove = 1001

    def __init__(
        self,
        result: DuplicateScanResult,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, min_card_width=560, max_card_width=680)
        self.setWindowTitle("Duplicates Found")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._rows: list[_DuplicateGroupRow] = []

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setPixmap(icon_pixmap("alert-circle", size=36, color=T.WARNING))
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel("Duplicates found")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {T.TEXT}; border: none;"
        )
        self._hero = QLabel(
            f"{result.removable_count} duplicate"
            f"{'s' if result.removable_count != 1 else ''} in "
            f"{result.group_count} group"
            f"{'s' if result.group_count != 1 else ''}"
        )
        self._hero.setWordWrap(True)
        self._hero.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {T.WARNING}; border: none;"
        )
        titles.addWidget(title)
        titles.addWidget(self._hero)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(titles, 1)

        subtitle = QLabel(
            "Same file content (SHA-256). Click a thumbnail to preview. "
            "Use Swap to reverse keep / remove in a row."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: 12px; border: none;"
        )

        tip = QLabel(
            "Remove soft-excludes duplicates (same as Remove from project). "
            "Original files stay on disk. Undo restores them."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(
            f"color: {T.TEXT}; background: {T.BACKGROUND}; border: 1px solid {T.BORDER};"
            " border-radius: 10px; padding: 12px 14px; font-size: 12px;"
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(280)
        scroll.setMaximumHeight(360)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        list_host = QWidget()
        list_layout = QVBoxLayout(list_host)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        for group in result.groups:
            row = _DuplicateGroupRow(group)
            row.preview_requested.connect(self._open_preview)
            self._rows.append(row)
            list_layout.addWidget(row)
        list_layout.addStretch(1)
        scroll.setWidget(list_host)

        keep_btn = QPushButton("Keep All")
        keep_btn.setObjectName("ghostButton")
        keep_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        keep_btn.clicked.connect(self.reject)

        self._remove_btn = QPushButton(
            f"Remove {result.removable_count} Duplicate"
            f"{'s' if result.removable_count != 1 else ''}"
        )
        self._remove_btn.setObjectName("dangerButton")
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setDefault(True)
        self._remove_btn.clicked.connect(lambda: self.done(self.Remove))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(keep_btn)
        buttons.addWidget(self._remove_btn)

        self._card_layout.addLayout(header)
        self._card_layout.addWidget(subtitle)
        self._card_layout.addWidget(scroll)
        self._card_layout.addWidget(tip)
        self._card_layout.addLayout(buttons)
        self._layout_card()

    def removable_photos(self) -> list[PhotoRecord]:
        """Photos currently marked Remove after any Swap edits."""
        removable: list[PhotoRecord] = []
        for row in self._rows:
            removable.extend(row.duplicates)
        return removable

    def group_count(self) -> int:
        return len(self._rows)

    def _open_preview(self, photo: PhotoRecord) -> None:
        path = _preview_path(photo)
        if path is None:
            MessageDialog.information(
                self,
                "Photo Unavailable",
                "This photo path is missing, so it cannot be previewed.",
            )
            return
        open_photo_lightbox(self, path)
