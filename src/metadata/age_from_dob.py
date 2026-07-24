"""Age helpers that combine DOB with capture metadata."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional


def age_years_at(
    date_of_birth: date,
    at: datetime | date,
) -> float:
    """
    Return fractional age in years at a given date.

    Uses whole days / 365.25 for a stable approximate age suitable for sorting.
    """
    if isinstance(at, datetime):
        at_date = at.date()
    else:
        at_date = at
    if at_date < date_of_birth:
        return 0.0
    days = (at_date - date_of_birth).days
    return round(days / 365.25, 3)


def max_age_years(
    date_of_birth: Optional[date],
    *,
    as_of: datetime | date | None = None,
) -> Optional[float]:
    """
    Oldest age the subject can possibly be in any photo.

    When DOB is known, no photo can show them older than their age today
    (or ``as_of``). Returns None when DOB is unknown.
    """
    if date_of_birth is None:
        return None
    return age_years_at(date_of_birth, as_of or date.today())


def clamp_age_to_dob(
    age: float,
    date_of_birth: Optional[date],
    *,
    as_of: datetime | date | None = None,
) -> tuple[float, bool]:
    """
    Clamp a facial age estimate into [0, max_age] when DOB is known.

    Returns (clamped_age, was_clamped).
    """
    clamped = float(max(0.0, age))
    ceiling = max_age_years(date_of_birth, as_of=as_of)
    if ceiling is None:
        return round(clamped, 2), False
    if clamped > ceiling:
        return round(ceiling, 2), True
    return round(clamped, 2), False


def age_from_dob_and_capture(
    date_of_birth: Optional[date],
    capture_date: Optional[datetime],
) -> Optional[float]:
    """Calculate age when both DOB and a capture date are available."""
    if date_of_birth is None or capture_date is None:
        return None
    return age_years_at(date_of_birth, capture_date)
