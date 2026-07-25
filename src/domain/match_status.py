"""Helpers for target identity match / no-match classification."""

from __future__ import annotations

from src.domain.models import PhotoRecord, ReviewStatus
from src.vision.identity_matcher import LOW_CONFIDENCE_THRESHOLD


def is_no_match_photo(
    photo: PhotoRecord,
    *,
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
) -> bool:
    """
    True when the photo should count as target-not-found.

    Score below the low-confidence floor is a hard no-match (e.g. 0.02 on a
    dog face), even if an older run left a softer review_status. User overrides
    (approved / manually corrected / excluded) win.
    """
    if photo.review_status in {
        ReviewStatus.EXCLUDED,
        ReviewStatus.APPROVED,
        ReviewStatus.MANUALLY_CORRECTED,
    }:
        return False
    if photo.review_status == ReviewStatus.NO_FACE:
        return False
    if photo.review_status == ReviewStatus.TARGET_NOT_FOUND:
        return True

    score = photo.identity_score
    if score is not None and float(score) < low_confidence_threshold:
        return True

    if (
        not photo.target_found
        and photo.review_status == ReviewStatus.PENDING
        and score is None
    ):
        return True

    return False
