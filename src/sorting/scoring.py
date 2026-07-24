"""Confidence-weighted chronological scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from src.domain.models import (
    DateReliability,
    PhotoAnalysis,
    PhotoRecord,
)
from src.metadata.age_from_dob import clamp_age_to_dob, max_age_years


@dataclass(frozen=True)
class SortDecision:
    """How a photo should be ordered on the youngest→oldest timeline."""

    sort_score: float
    effective_age: float | None
    age_confidence: float
    reason: str


def calculate_sort_score(photo: PhotoAnalysis) -> float:
    """Backward-compatible helper for PhotoAnalysis objects."""
    decision = decide_sort_from_analysis(photo)
    return decision.sort_score


def decide_sort_from_analysis(photo: PhotoAnalysis) -> SortDecision:
    if photo.manual_order is not None:
        return SortDecision(
            sort_score=float(photo.manual_order),
            effective_age=photo.manual_age,
            age_confidence=1.0,
            reason="manual_order",
        )
    if photo.manual_age is not None:
        return SortDecision(
            sort_score=float(photo.manual_age),
            effective_age=float(photo.manual_age),
            age_confidence=1.0,
            reason="manual_age",
        )
    if photo.age_from_dob is not None:
        return SortDecision(
            sort_score=float(photo.age_from_dob),
            effective_age=float(photo.age_from_dob),
            age_confidence=0.95,
            reason="dob_plus_exif",
        )
    if photo.estimated_age is not None:
        confidence = float(photo.age_confidence or 0.5)
        age = float(photo.estimated_age)
        return SortDecision(
            sort_score=age,
            effective_age=age,
            age_confidence=confidence,
            reason="facial_age_estimate",
        )
    if photo.filename_year is not None:
        # Without DOB we can only use year as a coarse proxy via epoch offset.
        return SortDecision(
            sort_score=float(photo.filename_year),
            effective_age=None,
            age_confidence=0.2,
            reason="filename_year",
        )
    return SortDecision(
        sort_score=float("inf"),
        effective_age=None,
        age_confidence=0.0,
        reason="unknown",
    )


def _facial_age_decision(
    estimated_age: float,
    age_confidence: float | None,
    date_of_birth: Optional[date],
) -> SortDecision:
    """Use facial age, clamped so it cannot exceed age-from-DOB today."""
    age, was_clamped = clamp_age_to_dob(estimated_age, date_of_birth)
    confidence = float(age_confidence or 0.5)
    if was_clamped:
        # Model was outside the physically possible range — trust it less.
        confidence = min(confidence, 0.25)
    return SortDecision(
        sort_score=age,
        effective_age=age,
        age_confidence=confidence,
        reason="facial_age_estimate",
    )


def decide_sort_for_record(
    photo: PhotoRecord,
    *,
    date_of_birth: Optional[date] = None,
) -> SortDecision:
    """
    Choose the best available age signal for sorting.

    Priority:
    1. Manual order / manual age
    2. DOB + reliable EXIF capture date
    3. Facial age estimate (clamped by DOB max age)
    4. Filename year vs DOB (approximate)
    5. Unknown (sort to end)
    """
    if photo.manual_order is not None:
        return SortDecision(
            sort_score=float(photo.manual_order),
            effective_age=photo.manual_age,
            age_confidence=1.0,
            reason="manual_order",
        )
    if photo.manual_age is not None:
        return SortDecision(
            sort_score=float(photo.manual_age),
            effective_age=float(photo.manual_age),
            age_confidence=1.0,
            reason="manual_age",
        )

    if (
        photo.age_from_dob is not None
        and photo.date_reliability == DateReliability.RELIABLE_EXIF
    ):
        return SortDecision(
            sort_score=float(photo.age_from_dob),
            effective_age=float(photo.age_from_dob),
            age_confidence=0.95,
            reason="dob_plus_exif",
        )

    if photo.estimated_age is not None:
        ceiling = max_age_years(date_of_birth)
        # Prefer coarse DOB+filename when the face model is impossibly old.
        if (
            ceiling is not None
            and date_of_birth is not None
            and photo.filename_year is not None
            and float(photo.estimated_age) > ceiling + 1.0
        ):
            approx_age = float(photo.filename_year - date_of_birth.year)
            if 0 <= approx_age <= ceiling:
                return SortDecision(
                    sort_score=approx_age,
                    effective_age=approx_age,
                    age_confidence=0.35,
                    reason="dob_plus_filename_year",
                )
        return _facial_age_decision(
            float(photo.estimated_age),
            photo.age_confidence,
            date_of_birth,
        )

    if date_of_birth is not None and photo.filename_year is not None:
        approx_age = float(photo.filename_year - date_of_birth.year)
        ceiling = max_age_years(date_of_birth)
        if ceiling is not None:
            approx_age = min(approx_age, ceiling)
        if 0 <= approx_age <= 120:
            return SortDecision(
                sort_score=approx_age,
                effective_age=approx_age,
                age_confidence=0.35,
                reason="dob_plus_filename_year",
            )

    # Weak filesystem dates are intentionally not trusted for primary ranking.
    return SortDecision(
        sort_score=float("inf"),
        effective_age=None,
        age_confidence=0.0,
        reason="unknown",
    )


def apply_sort_decision(
    photo: PhotoRecord,
    decision: SortDecision,
    *,
    date_of_birth: Optional[date] = None,
) -> PhotoRecord:
    """Write sort fields back onto a photo record (caller persists)."""
    del date_of_birth  # used by callers for API symmetry; sorting already decided
    photo.sort_score = (
        None if decision.sort_score == float("inf") else decision.sort_score
    )
    # Do not overwrite photo.estimated_age here — that value is the selected
    # face's raw AI age and must stay distinguishable across faces. DOB
    # ceilings are applied only to sort_score / effective_age via decide_*.
    if decision.reason in {"manual_order", "manual_age", "dob_plus_exif"}:
        photo.age_confidence = decision.age_confidence
    elif decision.reason == "facial_age_estimate":
        photo.age_confidence = decision.age_confidence
    elif photo.age_confidence is None:
        photo.age_confidence = decision.age_confidence
    return photo
