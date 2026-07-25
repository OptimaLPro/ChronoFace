"""Chronological thumbnail timeline for manual review."""

from __future__ import annotations

from datetime import date
from enum import Enum
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from src.domain.match_status import is_no_match_photo
from src.domain.models import DateReliability, PhotoRecord, ReviewStatus
from src.export.file_exporter import effective_age_for_name
from src.ui.needs_review_panel import categorize_review_photo
from src.ui.photo_lightbox import open_photo_lightbox
from src.ui.thumbnail_loader import load_thumbnail_pixmap
from src.ui.message_dialog import MessageDialog
from src.utils.paths import reveal_in_file_manager

# Thumbnail edge length (px). Ctrl+/− / Ctrl+wheel while hovering steps this.
_THUMB_SIZES = (72, 96, 128, 160, 192, 224)
_DEFAULT_THUMB_INDEX = 2  # 128
_CARD_RADIUS = 10
_CARD_PAD = 4
_TEXT_BLOCK = 28  # age label under the thumb
_GLOW_MARGIN = 8  # room around card for selection ring
# Store the painted thumb pixmap directly — DecorationRole returns QIcon.
_THUMB_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class ReviewFilter(str, Enum):
    ALL = "all"
    TARGET_FOUND = "target_found"
    NEEDS_REVIEW = "needs_review"
    LOW_CONFIDENCE = "low_confidence"
    HIGH_CONFIDENCE = "high_confidence"
    NO_FACE = "no_face"
    NOT_FOUND = "not_found"
    WITH_EXIF = "with_exif"
    MANUAL = "manual"
    EXCLUDED = "excluded"


FILTER_LABELS = {
    ReviewFilter.ALL: "All photos",
    ReviewFilter.TARGET_FOUND: "Target found",
    ReviewFilter.NEEDS_REVIEW: "Needs review",
    ReviewFilter.LOW_CONFIDENCE: "Low confidence",
    ReviewFilter.HIGH_CONFIDENCE: "High confidence matches",
    ReviewFilter.NO_FACE: "No face",
    ReviewFilter.NOT_FOUND: "Target not found",
    ReviewFilter.WITH_EXIF: "With EXIF dates",
    ReviewFilter.MANUAL: "Manually corrected",
    ReviewFilter.EXCLUDED: "Excluded",
}

# Colors used in the review legend (match _status_color below).
STATUS_LEGEND: tuple[tuple[str, str], ...] = (
    ("#1565c0", "Match"),
    ("#ef6c00", "Low confidence"),
    ("#c62828", "Not found"),
    ("#6a1b9a", "No face"),
    ("#2e7d32", "Manual"),
)

# List chrome only — never set ::item background in QSS (it kills status colors).
_LIST_STYLE = (
    "QListWidget {"
    "  background: transparent;"
    "  border: none;"
    "  border-radius: 0;"
    "  padding: 4px;"
    "  outline: none;"
    "}"
)


def _age_band_color(age: float | None) -> QColor:
    """Dot color matching the chronological age-band bar."""
    if age is None:
        return QColor("#9CA3AF")
    if age < 3:
        return QColor("#3B82F6")
    if age < 6:
        return QColor("#2563EB")
    if age < 10:
        return QColor("#4F46E5")
    if age < 14:
        return QColor("#6366F1")
    if age < 18:
        return QColor("#7C3AED")
    if age < 26:
        return QColor("#9333EA")
    return QColor("#A855F7")


def parse_review_filter(value: object) -> ReviewFilter | None:
    """Convert QComboBox user-data (often a plain str) into ReviewFilter."""
    if isinstance(value, ReviewFilter):
        return value
    if isinstance(value, str):
        try:
            return ReviewFilter(value)
        except ValueError:
            return None
    return None


def _has_reliable_age_metadata(photo: PhotoRecord) -> bool:
    """True when EXIF date makes age trustworthy even if identity score is low."""
    return photo.date_reliability == DateReliability.RELIABLE_EXIF


def _is_strong_match(photo: PhotoRecord) -> bool:
    """Blue “Match” — high identity score, or lower score with reliable EXIF age."""
    if not photo.target_found:
        return False
    if (photo.identity_score or 0) >= 0.5:
        return True
    return _has_reliable_age_metadata(photo)


def _status_color(photo: PhotoRecord) -> QColor:
    if photo.review_status == ReviewStatus.MANUALLY_CORRECTED:
        return QColor("#2e7d32")
    if photo.review_status == ReviewStatus.EXCLUDED:
        return QColor("#616161")
    if photo.review_status == ReviewStatus.NO_FACE:
        return QColor("#6a1b9a")
    if is_no_match_photo(photo):
        return QColor("#c62828")
    if photo.review_status == ReviewStatus.LOW_CONFIDENCE:
        # Age from DOB+EXIF is still trustworthy; show Match blue.
        if _has_reliable_age_metadata(photo):
            return QColor("#1565c0")
        return QColor("#ef6c00")
    if _is_strong_match(photo):
        return QColor("#1565c0")
    if photo.target_found:
        return QColor("#00838f")
    return QColor("#455a64")


def _matches_filter(
    photo: PhotoRecord,
    review_filter: ReviewFilter,
    *,
    date_of_birth: date | None = None,
) -> bool:
    if review_filter == ReviewFilter.ALL:
        # Soft-removed photos live under the Excluded filter only.
        return photo.review_status != ReviewStatus.EXCLUDED
    if review_filter == ReviewFilter.TARGET_FOUND:
        return bool(photo.target_found) and photo.review_status != ReviewStatus.EXCLUDED
    if review_filter == ReviewFilter.NEEDS_REVIEW:
        # Same queue as the Needs review metric / panel.
        return categorize_review_photo(photo, date_of_birth) is not None
    if review_filter == ReviewFilter.LOW_CONFIDENCE:
        return photo.review_status == ReviewStatus.LOW_CONFIDENCE
    if review_filter == ReviewFilter.HIGH_CONFIDENCE:
        return bool(photo.target_found and (photo.identity_score or 0) >= 0.55)
    if review_filter == ReviewFilter.NO_FACE:
        return photo.review_status == ReviewStatus.NO_FACE
    if review_filter == ReviewFilter.NOT_FOUND:
        return is_no_match_photo(photo)
    if review_filter == ReviewFilter.WITH_EXIF:
        return (
            photo.date_reliability == DateReliability.RELIABLE_EXIF
            and photo.review_status != ReviewStatus.EXCLUDED
        )
    if review_filter == ReviewFilter.MANUAL:
        return photo.review_status == ReviewStatus.MANUALLY_CORRECTED
    if review_filter == ReviewFilter.EXCLUDED:
        return photo.review_status == ReviewStatus.EXCLUDED
    return True


def _elide_name(name: str, max_chars: int = 22) -> str:
    if len(name) <= max_chars:
        return name
    return name[: max_chars - 1] + "…"


def _card_size(thumb_size: int) -> QSize:
    width = thumb_size + (_CARD_PAD * 2)
    height = thumb_size + (_CARD_PAD * 2) + _TEXT_BLOCK
    return QSize(width, height)


def _rounded_thumb(source: QPixmap, size: int, radius: int = 8) -> QPixmap:
    """Square, rounded thumbnail for the card image slot."""
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    if source.isNull():
        return result

    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    painter.setClipPath(path)
    painter.fillRect(0, 0, size, size, QColor(20, 20, 20))
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return result


class _ReviewCardDelegate(QStyledItemDelegate):
    """Paint status cards with on-screen text (crisp) instead of pixmap labels."""

    def __init__(self, timeline: "ReviewTimeline") -> None:
        super().__init__(timeline)
        self._timeline = timeline

    def sizeHint(
        self, option: QStyleOptionViewItem, index  # noqa: ARG002
    ) -> QSize:
        margin = _GLOW_MARGIN * 2
        return _card_size(self._timeline.thumb_size) + QSize(margin, margin)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        photo = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(photo, PhotoRecord):
            super().paint(painter, option, index)
            return

        thumb_size = self._timeline.thumb_size
        card = _card_size(thumb_size)
        # Center the card inside the item rect (list may pad items).
        x = option.rect.x() + max(0, (option.rect.width() - card.width()) // 2)
        y = option.rect.y() + max(0, (option.rect.height() - card.height()) // 2)
        card_rect = QRect(x, y, card.width(), card.height())
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        # Round geometry to whole pixels — fractional paint rects blur text on HiDPI.
        card_rect = QRect(
            int(round(card_rect.x())),
            int(round(card_rect.y())),
            card_rect.width(),
            card_rect.height(),
        )

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # White card with subtle border; blue ring when selected.
        path = QPainterPath()
        path.addRoundedRect(QRectF(card_rect), _CARD_RADIUS, _CARD_RADIUS)
        painter.fillPath(path, QColor("#FFFFFF"))
        painter.setPen(QPen(QColor("#E5E7EB"), 1))
        painter.drawPath(path)

        if selected:
            painter.setPen(QPen(QColor("#2F6BFF"), 3))
            painter.drawRoundedRect(
                QRectF(card_rect).adjusted(1.5, 1.5, -1.5, -1.5),
                _CARD_RADIUS,
                _CARD_RADIUS,
            )

        thumb_rect = QRect(
            card_rect.x() + _CARD_PAD,
            card_rect.y() + _CARD_PAD,
            thumb_size,
            thumb_size,
        )
        thumb = index.data(_THUMB_ROLE)
        if not isinstance(thumb, QPixmap) or thumb.isNull():
            decoration = index.data(Qt.ItemDataRole.DecorationRole)
            if isinstance(decoration, QPixmap):
                thumb = decoration
            elif isinstance(decoration, QIcon) and not decoration.isNull():
                thumb = decoration.pixmap(QSize(thumb_size, thumb_size))
            else:
                thumb = QPixmap()
        if isinstance(thumb, QPixmap) and not thumb.isNull():
            painter.drawPixmap(thumb_rect, thumb)
        else:
            painter.fillRect(thumb_rect, QColor(243, 244, 246))

        age = effective_age_for_name(photo, self._timeline._date_of_birth)
        age_text = f"{age:.1f} years" if age is not None else "Unknown"
        band = _age_band_color(age)

        text_top = thumb_rect.bottom() + 4
        text_rect = QRect(
            card_rect.x() + _CARD_PAD,
            text_top,
            thumb_size,
            _TEXT_BLOCK - 2,
        )

        # Colored age-band dot + crisp integer-pixel age label, centered as a group.
        age_font = QFont(option.font)
        age_font.setBold(True)
        age_font.setPixelSize(12)
        age_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        age_font.setStyleStrategy(
            QFont.StyleStrategy(
                QFont.StyleStrategy.PreferQuality
                | QFont.StyleStrategy.NoSubpixelAntialias
            )
        )
        painter.setFont(age_font)
        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(age_text)
        dot_size = 6
        gap = 4
        group_width = dot_size + gap + text_width
        group_x = text_rect.x() + max(0, (text_rect.width() - group_width) // 2)

        # AlignVCenter text placement, then center the dot on digit/cap midline.
        text_height = fm.ascent() + fm.descent()
        text_top = text_rect.y() + max(0, (text_rect.height() - text_height) // 2)
        baseline = text_top + fm.ascent()
        cap = fm.capHeight() if fm.capHeight() > 0 else fm.ascent()
        dot_y = baseline - (cap // 2) - (dot_size // 2)

        painter.setBrush(QBrush(band))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(group_x, dot_y, dot_size, dot_size)

        painter.setPen(QColor("#1F2937"))
        # Disable AA for the text pass — keeps glyphs sharp on Windows HiDPI.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        painter.drawText(
            QRect(
                group_x + dot_size + gap,
                text_rect.y(),
                text_width,
                text_rect.height(),
            ),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            age_text,
        )
        painter.restore()


class ReviewTimeline(QWidget):
    """Icon timeline of thumbnails with drag-and-drop reordering."""

    selection_changed = Signal(object)  # PhotoRecord | None
    order_changed = Signal(list)  # list[PhotoRecord] in new visual order
    remove_requested = Signal(object)  # PhotoRecord

    # Shared with ReviewDialog column headers for vertical alignment.
    HEADER_HEIGHT = 32

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._photos: list[PhotoRecord] = []
        self._filter = ReviewFilter.ALL
        self._date_of_birth: Optional[date] = None
        self._thumb_index = _DEFAULT_THUMB_INDEX
        self.setMinimumWidth(360)

        self._filter_combo = QComboBox()
        # Match toolbar button height; global QSS padding makes combos taller and
        # clips the bottom border inside the fixed HEADER_HEIGHT bar.
        self._filter_combo.setObjectName("toolbarCombo")
        self._filter_combo.setFixedHeight(self.HEADER_HEIGHT)
        # Store plain strings — Qt coerces str Enums to str in itemData anyway.
        for value, label in FILTER_LABELS.items():
            self._filter_combo.addItem(label, value.value)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)

        self._count_label = QLabel("0 photos")
        self._count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._count_label.setMinimumWidth(130)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Snap)
        self._list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._list.setSpacing(8)
        self._list.setWordWrap(False)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setStyleSheet(_LIST_STYLE)
        self._list.setItemDelegate(_ReviewCardDelegate(self))
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.setToolTip(
            "Ctrl + / − or Ctrl + mouse wheel to resize thumbnails"
        )
        self._list.itemSelectionChanged.connect(self._emit_selection)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        self._list.viewport().installEventFilter(self)
        self._apply_thumb_metrics()

        filter_label = QLabel("Filters")
        filter_label.setStyleSheet("font-weight: 600; color: #6B7280;")
        filter_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        # Built here; parented by DashboardPage (or ReviewDialog) toolbar.
        self._header_bar = QWidget()
        self._header_bar.setFixedHeight(self.HEADER_HEIGHT)
        self._header_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        header = QHBoxLayout(self._header_bar)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        vcenter = Qt.AlignmentFlag.AlignVCenter
        header.addWidget(filter_label, 0, vcenter)
        header.addWidget(self._filter_combo, 1, vcenter)
        header.addWidget(self._count_label, 0, vcenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._list, stretch=1)

        self._install_zoom_shortcuts()

    @property
    def header_bar(self) -> QWidget:
        return self._header_bar

    @property
    def thumb_size(self) -> int:
        return _THUMB_SIZES[self._thumb_index]

    @property
    def thumb_index(self) -> int:
        return self._thumb_index

    def set_thumb_index(self, index: int) -> None:
        """Restore a persisted thumbnail zoom step (clamped to valid range)."""
        self._thumb_index = max(0, min(int(index), len(_THUMB_SIZES) - 1))
        self._apply_thumb_metrics()
        if self._list.count():
            self._rebuild()

    def set_date_of_birth(self, date_of_birth: Optional[date]) -> None:
        self._date_of_birth = date_of_birth

    def set_photos(self, photos: list[PhotoRecord]) -> None:
        self._photos = list(photos)
        self._rebuild()

    def photos_in_visual_order(self) -> list[PhotoRecord]:
        ordered: list[PhotoRecord] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            photo = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(photo, PhotoRecord):
                ordered.append(photo)
        return ordered

    def selected_photos(self) -> list[PhotoRecord]:
        photos: list[PhotoRecord] = []
        for item in self._list.selectedItems():
            photo = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(photo, PhotoRecord):
                photos.append(photo)
        return photos

    def refresh_item(self, photo: PhotoRecord) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            current = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(current, PhotoRecord) and current.id == photo.id:
                self._populate_item(item, photo)
                return

    def apply_photo_update(self, photo: PhotoRecord) -> None:
        """Sync a photo edit; drop excluded items and advance selection."""
        for index, current in enumerate(self._photos):
            if current.id == photo.id:
                self._photos[index] = photo
                break

        visible_index = -1
        for index in range(self._list.count()):
            item = self._list.item(index)
            current = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(current, PhotoRecord) and current.id == photo.id:
                visible_index = index
                break

        still_matches = _matches_filter(
            photo, self._filter, date_of_birth=self._date_of_birth
        )
        if visible_index >= 0 and not still_matches:
            self._rebuild_after_removal(visible_index)
            return
        if visible_index < 0 and still_matches:
            self._rebuild()
            return
        if visible_index >= 0:
            self.refresh_item(photo)

    def set_filter(self, review_filter: ReviewFilter) -> None:
        """Set the active filter and sync the toolbar combo."""
        for index in range(self._filter_combo.count()):
            if self._filter_combo.itemData(index) == review_filter.value:
                if self._filter_combo.currentIndex() != index:
                    self._filter_combo.setCurrentIndex(index)
                elif self._filter != review_filter:
                    self._filter = review_filter
                    self._rebuild()
                return
        self._filter = review_filter
        self._rebuild()

    def current_filter(self) -> ReviewFilter:
        return self._filter

    def _rebuild_after_removal(self, removed_index: int) -> None:
        """Rebuild the grid and select the next photo (or clear if last)."""
        self._list.blockSignals(True)
        self._list.clear()
        visible = [
            photo
            for photo in self._photos
            if _matches_filter(photo, self._filter, date_of_birth=self._date_of_birth)
        ]
        for photo in visible:
            item = QListWidgetItem()
            self._populate_item(item, photo)
            self._list.addItem(item)

        if removed_index < self._list.count():
            item = self._list.item(removed_index)
            item.setSelected(True)
            self._list.scrollToItem(item)
        # else: was last item — leave selection empty

        self._list.blockSignals(False)
        self._count_label.setText(f"{len(visible)} shown / {len(self._photos)} total")
        self._emit_selection()

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        photo = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(photo, PhotoRecord):
            return
        self._preview_photo(photo)

    def _photo_preview_path(self, photo: PhotoRecord) -> Path | None:
        if photo.original_path.is_file():
            return photo.original_path
        if photo.thumbnail_path is not None and photo.thumbnail_path.is_file():
            return photo.thumbnail_path
        return None

    def _preview_photo(self, photo: PhotoRecord) -> None:
        path = self._photo_preview_path(photo)
        if path is None:
            MessageDialog.information(
                self,
                "Photo Unavailable",
                "This photo path is missing, so it cannot be previewed.",
            )
            return
        open_photo_lightbox(self.window(), path)

    def _open_in_explorer(self, photo: PhotoRecord) -> None:
        path = photo.original_path
        try:
            reveal_in_file_manager(path)
        except FileNotFoundError:
            MessageDialog.warning(
                self,
                "Photo Missing",
                f"The file could not be found:\n{path}",
            )
        except OSError as exc:
            MessageDialog.warning(self, "Could Not Open Folder", str(exc))

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        photo = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(photo, PhotoRecord):
            return

        if not item.isSelected():
            self._list.clearSelection()
            item.setSelected(True)

        menu = QMenu(self)
        preview_action = menu.addAction("Preview photo")
        explorer_action = menu.addAction("Open in explorer")
        menu.addSeparator()
        remove_action = menu.addAction("Remove from project")
        chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == preview_action:
            self._preview_photo(photo)
        elif chosen == explorer_action:
            self._open_in_explorer(photo)
        elif chosen == remove_action:
            self.remove_requested.emit(photo)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is self._list.viewport()
            and event.type() == QEvent.Type.Wheel
            and isinstance(event, QWheelEvent)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            delta = event.angleDelta().y()
            if delta == 0:
                delta = event.pixelDelta().y()
            if delta > 0:
                self._adjust_zoom(1)
                return True
            if delta < 0:
                self._adjust_zoom(-1)
                return True
        return super().eventFilter(watched, event)

    def _install_zoom_shortcuts(self) -> None:
        """Ctrl+/− (and Ctrl+=) while the pointer is over the photo canvas."""
        self._zoom_shortcuts: list[QShortcut] = []
        for sequence, delta in (
            ("Ctrl++", 1),
            ("Ctrl+=", 1),
            ("Ctrl+-", -1),
            ("Ctrl+_", -1),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(
                lambda checked=False, step=delta: self._zoom_if_hovered(step)
            )
            self._zoom_shortcuts.append(shortcut)

    def _zoom_if_hovered(self, delta: int) -> None:
        if self.underMouse() or self._list.underMouse():
            self._adjust_zoom(delta)

    def _adjust_zoom(self, delta: int) -> None:
        new_index = self._thumb_index + delta
        if new_index < 0 or new_index >= len(_THUMB_SIZES):
            return
        self._thumb_index = new_index
        self._apply_thumb_metrics()
        self._rebuild()

    def _apply_thumb_metrics(self) -> None:
        # Icon is the photo only; labels are drawn by the delegate.
        size = self.thumb_size
        self._list.setIconSize(QSize(size, size))

    def _on_filter_changed(self) -> None:
        parsed = parse_review_filter(self._filter_combo.currentData())
        if parsed is not None:
            self._filter = parsed
        self._rebuild()

    def _rebuild(self) -> None:
        selected_id = None
        selected = self.selected_photos()
        if selected:
            selected_id = selected[0].id

        self._list.blockSignals(True)
        self._list.clear()
        visible = [
            photo
            for photo in self._photos
            if _matches_filter(photo, self._filter, date_of_birth=self._date_of_birth)
        ]
        for photo in visible:
            item = QListWidgetItem()
            self._populate_item(item, photo)
            self._list.addItem(item)
            if photo.id is not None and photo.id == selected_id:
                item.setSelected(True)
        self._list.blockSignals(False)
        self._count_label.setText(f"{len(visible)} shown / {len(self._photos)} total")
        self._emit_selection()

    def _populate_item(self, item: QListWidgetItem, photo: PhotoRecord) -> None:
        thumb_source = photo.thumbnail_path or photo.original_path
        pixmap = load_thumbnail_pixmap(thumb_source, size=self.thumb_size)
        thumb = _rounded_thumb(pixmap, self.thumb_size)
        item.setIcon(thumb)
        item.setData(_THUMB_ROLE, thumb)
        # Labels are painted by _ReviewCardDelegate (sharp on-screen text).
        item.setText("")
        item.setData(Qt.ItemDataRole.UserRole, photo)
        item.setBackground(QBrush(QColor("#FFFFFF")))
        margin = _GLOW_MARGIN * 2
        item.setSizeHint(_card_size(self.thumb_size) + QSize(margin, margin))

    def _emit_selection(self) -> None:
        selected = self.selected_photos()
        self.selection_changed.emit(selected[0] if selected else None)

    def _on_rows_moved(self, *_args) -> None:
        visual = self.photos_in_visual_order()
        if self._filter == ReviewFilter.ALL:
            self._photos = visual
        self.order_changed.emit(visual)
