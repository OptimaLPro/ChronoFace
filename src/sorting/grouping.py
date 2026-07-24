"""Life-stage / age-range grouping (Phase 5)."""

from __future__ import annotations

AGE_GROUPS: list[tuple[float, float | None, str]] = [
    (0, 2, "0-2"),
    (3, 5, "3-5"),
    (6, 9, "6-9"),
    (10, 13, "10-13"),
    (14, 17, "14-17"),
    (18, 25, "18-25"),
    (26, 35, "26-35"),
    (36, 50, "36-50"),
    (51, None, "51+"),
]


def age_group_label(age: float | None) -> str:
    """Map an age to a coarse life-stage bucket."""
    if age is None:
        return "unknown"
    for low, high, label in AGE_GROUPS:
        if high is None:
            if age >= low:
                return label
        elif low <= age <= high:
            return label
    return "unknown"
