"""Tests for review filter helpers."""

from pathlib import Path

from src.domain.models import PhotoRecord, ReviewStatus
from src.ui.review_timeline import (
    ReviewFilter,
    _matches_filter,
    parse_review_filter,
)


def test_review_filter_low_confidence() -> None:
    photo = PhotoRecord(
        project_id="p",
        original_path=Path("a.jpg"),
        review_status=ReviewStatus.LOW_CONFIDENCE,
    )
    assert _matches_filter(photo, ReviewFilter.LOW_CONFIDENCE)
    assert not _matches_filter(photo, ReviewFilter.NO_FACE)


def test_review_filter_manual() -> None:
    photo = PhotoRecord(
        project_id="p",
        original_path=Path("a.jpg"),
        review_status=ReviewStatus.MANUALLY_CORRECTED,
        manual_age=4.0,
    )
    assert _matches_filter(photo, ReviewFilter.MANUAL)
    assert _matches_filter(photo, ReviewFilter.ALL)


def test_review_filter_all_hides_excluded() -> None:
    photo = PhotoRecord(
        project_id="p",
        original_path=Path("a.jpg"),
        review_status=ReviewStatus.EXCLUDED,
    )
    assert not _matches_filter(photo, ReviewFilter.ALL)
    assert _matches_filter(photo, ReviewFilter.EXCLUDED)


def test_parse_review_filter_accepts_qt_string_userdata() -> None:
    # QComboBox stores str Enums as plain strings in itemData.
    assert parse_review_filter("low_confidence") == ReviewFilter.LOW_CONFIDENCE
    assert parse_review_filter(ReviewFilter.NO_FACE) == ReviewFilter.NO_FACE
    assert parse_review_filter("not-a-filter") is None
    assert parse_review_filter(None) is None
