"""Stable ranking of analyzed photos."""

from __future__ import annotations

from datetime import date
from typing import Optional

from src.domain.models import PhotoAnalysis, PhotoRecord
from src.sorting.scoring import (
    apply_sort_decision,
    calculate_sort_score,
    decide_sort_for_record,
    decide_sort_from_analysis,
)


def rank_photos(photos: list[PhotoAnalysis]) -> list[PhotoAnalysis]:
    """Sort PhotoAnalysis objects youngest → oldest."""
    decorated = []
    for index, photo in enumerate(photos):
        decision = decide_sort_from_analysis(photo)
        score = (
            photo.sort_score
            if photo.sort_score is not None
            else decision.sort_score
        )
        decorated.append((score, index, photo))
    decorated.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in decorated]


def rank_photo_records(
    photos: list[PhotoRecord],
    *,
    date_of_birth: Optional[date] = None,
) -> list[PhotoRecord]:
    """
    Assign sort scores and return photos youngest → oldest.

    Photos without an age signal sort after dated ones (stable by path).
    """
    decorated: list[tuple[float, int, PhotoRecord]] = []
    for index, photo in enumerate(photos):
        decision = decide_sort_for_record(photo, date_of_birth=date_of_birth)
        apply_sort_decision(photo, decision, date_of_birth=date_of_birth)
        score = (
            float("inf")
            if photo.sort_score is None
            else float(photo.sort_score)
        )
        decorated.append((score, index, photo))

    decorated.sort(
        key=lambda item: (
            item[0],
            str(item[2].original_path).lower(),
            item[1],
        )
    )
    return [item[2] for item in decorated]


# Re-export for older imports/tests.
__all__ = [
    "rank_photos",
    "rank_photo_records",
    "calculate_sort_score",
]
