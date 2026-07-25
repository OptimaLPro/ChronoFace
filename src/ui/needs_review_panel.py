"""Horizontal strip of photos that need manual review."""

from __future__ import annotations

from datetime import date
from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
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

from src.domain.models import DateReliability, PhotoRecord, ReviewStatus
from src.domain.match_status import is_no_match_photo
from src.export.file_exporter import effective_age_for_name
from src.ui.thumbnail_loader import load_thumbnail_pixmap

_THUMB_W = 88
_THUMB_H = 72
_THUMB_RADIUS = 8  # match timeline _rounded_thumb default


def _rounded_rect_pixmap(
    source: QPixmap,
    width: int,
    height: int,
    radius: int = _THUMB_RADIUS,
) -> QPixmap:
    """Crop/scale to WxH and clip to rounded rect (QLabel CSS can't clip pixmaps)."""
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


def _has_reliable_exif(photo: PhotoRecord) -> bool:
    """EXIF date makes chronological age trustworthy even with a low face score."""
    return photo.date_reliability == DateReliability.RELIABLE_EXIF


class ReviewCategory(str, Enum):
    LOW_MATCH = "low_match"
    MULTIPLE_FACES = "multiple_faces"
    NO_CLEAR_FACE = "no_clear_face"
    SIDE_PROFILE = "side_profile"
    LOW_QUALITY = "low_quality"
    UNKNOWN_AGE = "unknown_age"
    NOT_FOUND = "not_found"


CATEGORY_LABELS = {
    ReviewCategory.LOW_MATCH: ("Low match", "#EA580C"),
    ReviewCategory.MULTIPLE_FACES: ("Multiple faces", "#7C3AED"),
    ReviewCategory.NO_CLEAR_FACE: ("No clear face", "#DC2626"),
    ReviewCategory.SIDE_PROFILE: ("Side profile", "#0D9488"),
    ReviewCategory.LOW_QUALITY: ("Low quality", "#65A30D"),
    ReviewCategory.UNKNOWN_AGE: ("Unknown age", "#64748B"),
    ReviewCategory.NOT_FOUND: ("Not found", "#DC2626"),
}


def categorize_review_photo(
    photo: PhotoRecord,
    date_of_birth: date | None = None,
) -> ReviewCategory | None:
    """Map a photo into a needs-review visual category, or None if clear."""
    if photo.review_status == ReviewStatus.EXCLUDED:
        return None
    if photo.review_status == ReviewStatus.APPROVED:
        # Still surface if age is completely unknown.
        if effective_age_for_name(photo, date_of_birth) is None:
            return ReviewCategory.UNKNOWN_AGE
        return None

    if photo.review_status == ReviewStatus.NO_FACE:
        return ReviewCategory.NO_CLEAR_FACE
    if photo.review_status == ReviewStatus.ERROR:
        return ReviewCategory.NO_CLEAR_FACE
    # Hard no-match (score below low-confidence floor, or TARGET_NOT_FOUND).
    # Must win over "Low match" so dog/object faces with 0.02 count as Not found.
    if is_no_match_photo(photo):
        return ReviewCategory.NOT_FOUND

    if photo.review_status == ReviewStatus.LOW_CONFIDENCE:
        # Reliable EXIF age outweighs a weak face match — treat as resolved.
        if _has_reliable_exif(photo):
            if effective_age_for_name(photo, date_of_birth) is None:
                return ReviewCategory.UNKNOWN_AGE
            return None
        quality = photo.face_quality
        if quality is not None and quality < 0.35:
            return ReviewCategory.LOW_QUALITY
        if quality is not None and quality < 0.5:
            return ReviewCategory.SIDE_PROFILE
        return ReviewCategory.LOW_MATCH

    if photo.review_status == ReviewStatus.NEEDS_REVIEW:
        return ReviewCategory.MULTIPLE_FACES

    # Unknown chronological age — user must supply age or date.
    if effective_age_for_name(photo, date_of_birth) is None:
        return ReviewCategory.UNKNOWN_AGE

    score = photo.identity_score
    if score is not None and score < 0.55:
        # Low face score + EXIF date → trusted chronological match, not review.
        if _has_reliable_exif(photo):
            return None
        return ReviewCategory.LOW_MATCH

    return None


def photos_needing_review(
    photos: list[PhotoRecord],
    date_of_birth: date | None = None,
) -> list[tuple[PhotoRecord, ReviewCategory]]:
    items: list[tuple[PhotoRecord, ReviewCategory]] = []
    for photo in photos:
        category = categorize_review_photo(photo, date_of_birth)
        if category is not None:
            items.append((photo, category))
    return items


class _ReviewThumb(QFrame):
    clicked = Signal(object)  # PhotoRecord

    def __init__(
        self,
        photo: PhotoRecord,
        category: ReviewCategory,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._photo = photo
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(96, 112)
        self.setStyleSheet(
            "QFrame {"
            "  background: #FFFFFF;"
            "  border: 1px solid #EEF0F4;"
            "  border-radius: 10px;"
            "}"
            "QFrame:hover { border-color: #2F6BFF; }"
        )

        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = load_thumbnail_pixmap(
            photo.thumbnail_path or photo.original_path, size=_THUMB_W
        )
        if not pix.isNull():
            thumb.setPixmap(_rounded_rect_pixmap(pix, _THUMB_W, _THUMB_H))
        else:
            thumb.setText("?")

        label_text, color = CATEGORY_LABELS[category]
        badge = QLabel(label_text)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"QLabel {{"
            f"  background: {color}; color: white; font-size: 10px;"
            f"  font-weight: 700; border-radius: 4px; padding: 2px 4px;"
            f"}}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addWidget(thumb)
        layout.addWidget(badge)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._photo)
        super().mouseReleaseEvent(event)


class NeedsReviewPanel(QWidget):
    """Dedicated review area under the chronological timeline."""

    photo_selected = Signal(object)  # PhotoRecord
    review_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(160)
        self._date_of_birth: date | None = None

        self._title = QLabel("Needs Review (0)")
        self._title.setObjectName("sectionTitle")

        self._review_all = QPushButton("Review All")
        self._review_all.setFlat(True)
        self._review_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._review_all.setStyleSheet(
            "QPushButton {"
            "  color: #2F6BFF; font-weight: 600; border: none; background: transparent;"
            "  padding: 4px 8px;"
            "}"
            "QPushButton:hover { color: #2558E0; }"
        )
        self._review_all.clicked.connect(self.review_all_requested.emit)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._review_all)

        self._row = QHBoxLayout()
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(10)
        self._row.addStretch(1)

        inner = QWidget()
        inner.setObjectName("needsReviewInner")
        inner.setLayout(self._row)

        scroll = QScrollArea()
        scroll.setObjectName("needsReviewScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(120)
        scroll.setWidget(inner)
        scroll.viewport().setAutoFillBackground(False)

        card = QFrame()
        card.setObjectName("needsReviewCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            "QFrame#needsReviewCard {"
            "  background: #F3F4F6;"
            "  border: 1px solid #EEF0F4;"
            "  border-radius: 12px;"
            "}"
            "QScrollArea#needsReviewScroll, QScrollArea#needsReviewScroll > QWidget {"
            "  background: transparent; border: none;"
            "}"
            "QWidget#needsReviewInner { background: transparent; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(8)
        card_layout.addLayout(header)
        card_layout.addWidget(scroll)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        self._empty = QLabel("No photos need review.")
        self._empty.setObjectName("mutedLabel")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._row.insertWidget(0, self._empty)

    def set_date_of_birth(self, date_of_birth: date | None) -> None:
        self._date_of_birth = date_of_birth

    def set_photos(self, photos: list[PhotoRecord]) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        items = photos_needing_review(photos, self._date_of_birth)
        self._title.setText(f"Needs Review ({len(items)})")
        self._review_all.setVisible(bool(items))

        if not items:
            empty = QLabel("No photos need review.")
            empty.setObjectName("mutedLabel")
            self._row.addWidget(empty)
            self._row.addStretch(1)
            return

        max_show = 8
        for photo, category in items[:max_show]:
            thumb = _ReviewThumb(photo, category)
            thumb.clicked.connect(self.photo_selected.emit)
            self._row.addWidget(thumb)

        remaining = len(items) - max_show
        if remaining > 0:
            more = QLabel(f"+{remaining} more")
            more.setAlignment(Qt.AlignmentFlag.AlignCenter)
            more.setFixedSize(72, 112)
            more.setStyleSheet(
                "QLabel {"
                "  background: #F3F4F6; border: 1px dashed #D1D5DB;"
                "  border-radius: 10px; color: #6B7280; font-weight: 700;"
                "}"
            )
            self._row.addWidget(more)

        self._row.addStretch(1)
