"""Tests for no-match classification and review categorization."""

from __future__ import annotations

from pathlib import Path

from src.domain.match_status import is_no_match_photo
from src.domain.models import PhotoRecord, ReviewStatus
from src.export.file_exporter import effective_age_for_name
from src.ui.needs_review_panel import ReviewCategory, categorize_review_photo
from src.ui.review_timeline import ReviewFilter, _matches_filter


def _photo(**kwargs) -> PhotoRecord:
    defaults = {
        "project_id": "p",
        "original_path": Path("dogs.jpg"),
        "target_found": False,
        "identity_score": 0.02,
        "estimated_age": 30.0,
        "age_from_dob": 12.6,
        "review_status": ReviewStatus.LOW_CONFIDENCE,
    }
    defaults.update(kwargs)
    return PhotoRecord(**defaults)


def test_score_below_floor_is_no_match() -> None:
    photo = _photo()
    assert is_no_match_photo(photo) is True


def test_low_confidence_band_is_not_hard_no_match() -> None:
    photo = _photo(
        identity_score=0.32,
        review_status=ReviewStatus.LOW_CONFIDENCE,
    )
    assert is_no_match_photo(photo) is False


def test_user_override_wins() -> None:
    photo = _photo(review_status=ReviewStatus.APPROVED, target_found=True)
    assert is_no_match_photo(photo) is False


def test_categorize_dog_face_as_not_found() -> None:
    photo = _photo()
    assert categorize_review_photo(photo) == ReviewCategory.NOT_FOUND


def test_not_found_filter_includes_score_no_match() -> None:
    photo = _photo(review_status=ReviewStatus.NEEDS_REVIEW, target_found=True)
    assert _matches_filter(photo, ReviewFilter.NOT_FOUND)


def test_effective_age_cleared_for_no_match() -> None:
    photo = _photo()
    assert effective_age_for_name(photo) is None


def test_manual_age_still_used_for_no_match() -> None:
    photo = _photo(manual_age=8.0)
    assert effective_age_for_name(photo) == 8.0
