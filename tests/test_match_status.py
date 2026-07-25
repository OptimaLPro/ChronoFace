"""Tests for no-match classification and review categorization."""

from __future__ import annotations

from pathlib import Path

from src.domain.match_status import is_no_match_photo
from src.domain.models import DateReliability, PhotoRecord, ReviewStatus
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


def test_save_order_manually_corrected_dog_still_no_match() -> None:
    """Save Order stamps manually_corrected; low score must still be Not found."""
    photo = _photo(
        identity_score=0.02,
        target_found=False,
        review_status=ReviewStatus.MANUALLY_CORRECTED,
    )
    assert is_no_match_photo(photo) is True
    assert categorize_review_photo(photo) == ReviewCategory.NOT_FOUND


def test_manually_corrected_match_is_not_no_match() -> None:
    photo = _photo(
        identity_score=0.72,
        target_found=True,
        review_status=ReviewStatus.MANUALLY_CORRECTED,
    )
    assert is_no_match_photo(photo) is False


def test_target_miss_without_low_confidence_is_no_match() -> None:
    photo = _photo(
        identity_score=0.40,
        target_found=False,
        review_status=ReviewStatus.MANUALLY_CORRECTED,
    )
    assert is_no_match_photo(photo) is True


def test_categorize_dog_face_as_not_found() -> None:
    photo = _photo()
    assert categorize_review_photo(photo) == ReviewCategory.NOT_FOUND


def test_not_found_filter_includes_score_no_match() -> None:
    photo = _photo(review_status=ReviewStatus.NEEDS_REVIEW, target_found=True)
    assert _matches_filter(photo, ReviewFilter.NOT_FOUND)


def test_no_match_shows_face_age_not_dob_age() -> None:
    """No-match keeps face AI age for display; DOB chronology stays hidden."""
    photo = _photo(estimated_age=30.0, age_from_dob=12.6)
    assert effective_age_for_name(photo) == 30.0

    photo_dob_only = _photo(estimated_age=None, age_from_dob=12.6)
    assert effective_age_for_name(photo_dob_only) is None


def test_manual_age_still_used_for_no_match() -> None:
    photo = _photo(manual_age=8.0)
    assert effective_age_for_name(photo) == 8.0


def test_exif_match_skips_needs_review_even_with_multiple_faces() -> None:
    """EXIF age is trusted — multi-face / mid score must not enter Needs review."""
    photo = _photo(
        identity_score=0.53,
        target_found=True,
        age_from_dob=0.0,
        review_status=ReviewStatus.NEEDS_REVIEW,
        date_reliability=DateReliability.RELIABLE_EXIF,
    )
    assert categorize_review_photo(photo) is None


def test_exif_low_confidence_skips_needs_review() -> None:
    photo = _photo(
        identity_score=0.34,
        target_found=False,
        age_from_dob=6.0,
        review_status=ReviewStatus.LOW_CONFIDENCE,
        date_reliability=DateReliability.RELIABLE_EXIF,
    )
    assert is_no_match_photo(photo) is False
    assert categorize_review_photo(photo) is None


def test_no_match_with_exif_still_needs_review() -> None:
    """Wrong-person / dog faces stay in the queue even when EXIF exists."""
    photo = _photo(
        identity_score=0.02,
        target_found=False,
        review_status=ReviewStatus.TARGET_NOT_FOUND,
        date_reliability=DateReliability.RELIABLE_EXIF,
    )
    assert categorize_review_photo(photo) == ReviewCategory.NOT_FOUND
