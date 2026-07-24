"""Deep-copy helpers for undo snapshots."""

from __future__ import annotations

from copy import deepcopy

from src.domain.models import PhotoRecord, ProjectConfig


def copy_photo(photo: PhotoRecord) -> PhotoRecord:
    return deepcopy(photo)


def copy_photos(photos: list[PhotoRecord]) -> list[PhotoRecord]:
    return [deepcopy(photo) for photo in photos]


def copy_project(config: ProjectConfig) -> ProjectConfig:
    return deepcopy(config)
