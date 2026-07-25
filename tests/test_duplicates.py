"""Exact duplicate detection and keeper selection."""

from __future__ import annotations

from pathlib import Path

from src.domain.models import DateReliability, PhotoRecord, ReviewStatus
from src.sorting.duplicates import (
    choose_keeper,
    find_exact_duplicates,
    looks_like_copy_filename,
    photos_to_exclude,
)


def _photo(
    name: str,
    *,
    digest: str | None = "abc",
    status: ReviewStatus = ReviewStatus.PENDING,
    target: bool = False,
    identity: float | None = None,
    path_prefix: str = "",
    photo_id: int | None = None,
    sort_score: float | None = None,
    manual_order: int | None = None,
    date_reliability: DateReliability = DateReliability.NONE,
) -> PhotoRecord:
    return PhotoRecord(
        project_id="p",
        original_path=Path(path_prefix) / name if path_prefix else Path(name),
        file_hash=digest,
        review_status=status,
        target_found=target,
        identity_score=identity,
        id=photo_id,
        sort_score=sort_score,
        manual_order=manual_order,
        date_reliability=date_reliability,
    )


def test_looks_like_copy_filename() -> None:
    assert looks_like_copy_filename("holiday (1).jpg")
    assert looks_like_copy_filename("holiday - Copy.jpg")
    assert looks_like_copy_filename("Copy of holiday.jpg")
    assert looks_like_copy_filename("holiday_copy.jpg")
    assert not looks_like_copy_filename("holiday.jpg")
    assert not looks_like_copy_filename("IMG_2048.jpg")
    assert not looks_like_copy_filename("holiday_2.jpg")


def test_find_exact_duplicates_groups_by_hash() -> None:
    keep = _photo("keep.jpg", digest="h1", target=True, identity=0.9, photo_id=1)
    copy_a = _photo("keep (1).jpg", digest="h1", photo_id=2)
    unique = _photo("other.jpg", digest="h2", photo_id=3)
    excluded = _photo(
        "gone.jpg",
        digest="h1",
        status=ReviewStatus.EXCLUDED,
        photo_id=4,
    )

    result = find_exact_duplicates([keep, copy_a, unique, excluded])
    assert result.group_count == 1
    assert result.removable_count == 1
    assert result.groups[0].keeper.id == 1
    assert [p.id for p in result.groups[0].duplicates] == [2]
    assert photos_to_exclude(result)[0].id == 2


def test_choose_keeper_prefers_approved_and_primary_name() -> None:
    copy_photo = _photo(
        "face (1).jpg",
        digest="x",
        target=True,
        identity=0.95,
        status=ReviewStatus.PENDING,
        photo_id=1,
    )
    primary = _photo(
        "face.jpg",
        digest="x",
        target=True,
        identity=0.8,
        status=ReviewStatus.APPROVED,
        photo_id=2,
    )
    assert choose_keeper([copy_photo, primary]).id == 2


def test_choose_keeper_prefers_non_copy_name_when_equal() -> None:
    primary = _photo("shot.jpg", digest="z", target=True, identity=0.7, photo_id=1)
    copy_photo = _photo(
        "shot - Copy.jpg",
        digest="z",
        target=True,
        identity=0.7,
        photo_id=2,
    )
    assert choose_keeper([copy_photo, primary]).id == 1


def test_no_duplicates_when_hashes_unique() -> None:
    photos = [
        _photo("a.jpg", digest="1", photo_id=1),
        _photo("b.jpg", digest="2", photo_id=2),
    ]
    result = find_exact_duplicates(photos)
    assert not result.has_duplicates
    assert result.removable_count == 0


def test_skipped_no_hash_counted() -> None:
    photos = [
        _photo("a.jpg", digest=None, photo_id=1),
        _photo("b.jpg", digest="", photo_id=2),
        _photo("c.jpg", digest="same", photo_id=3),
        _photo("d.jpg", digest="same", photo_id=4),
    ]
    result = find_exact_duplicates(photos)
    assert result.skipped_no_hash == 2
    assert result.removable_count == 1
