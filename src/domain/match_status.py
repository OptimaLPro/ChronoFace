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
    True when the photo should count as target-not-found ("No match" badge).

    Score below the low-confidence floor is a hard no-match (e.g. 0.02 on a
    dog face), even if Save Order stamped MANUALLY_CORRECTED on the row.

    User overrides that confirm the target (approved) or remove the photo
    (excluded) win. LOW_CONFIDENCE is "Low match", not hard no-match.
    """
    if photo.review_status in {
        ReviewStatus.EXCLUDED,
        ReviewStatus.APPROVED,
    }:
        return False
    if photo.review_status == ReviewStatus.NO_FACE:
        return False

    score = photo.identity_score
    if score is not None and float(score) < low_confidence_threshold:
        return True

    if photo.review_status == ReviewStatus.TARGET_NOT_FOUND:
        return True

    # Mid band (e.g. 0.30–0.36) is Low match, not Not found.
    if photo.review_status == ReviewStatus.LOW_CONFIDENCE:
        return False

    # Misses (including save-order manually_corrected rows with target_found=0)
    # show the red "No match" badge and count toward Not found.
    if not photo.target_found:
        return True

    return False
