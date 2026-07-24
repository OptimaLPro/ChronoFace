"""Filename / folder-name date heuristics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# Years that are plausible for personal photos in this product's domain.
_MIN_YEAR = 1950
_MAX_YEAR = 2100

_YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_ISO_DATE_PATTERN = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[-_.](\d{2})[-_.](\d{2})(?!\d)"
)


def _valid_year(year: int) -> bool:
    return _MIN_YEAR <= year <= _MAX_YEAR


def guess_year_from_name(path: Path) -> Optional[int]:
    """
    Best-effort year extraction from filename or parent folder name.

    Prefers an ISO-like date in the filename, then a standalone 4-digit year
    in the filename, then the parent folder name.
    """
    path = Path(path)
    for candidate in (path.stem, path.parent.name):
        iso = _ISO_DATE_PATTERN.search(candidate)
        if iso:
            year = int(iso.group(1))
            if _valid_year(year):
                return year

        matches = [int(match) for match in _YEAR_PATTERN.findall(candidate)]
        valid = [year for year in matches if _valid_year(year)]
        if valid:
            # Prefer the last year-like token (often the event year suffix).
            return valid[-1]
    return None


def guess_years_from_path(path: Path) -> list[int]:
    """Return all plausible years found in the filename and parent folder."""
    path = Path(path)
    years: list[int] = []
    for candidate in (path.stem, path.parent.name):
        for match in _YEAR_PATTERN.findall(candidate):
            year = int(match)
            if _valid_year(year) and year not in years:
                years.append(year)
    return years
