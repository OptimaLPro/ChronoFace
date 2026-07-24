"""Undo command for bulk photo field updates (order / re-rank)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QUndoCommand

from src.commands.snapshots import copy_photos
from src.database.photo_repository import PhotoRepository
from src.domain.models import PhotoRecord


class BulkPhotosSnapshotCommand(QUndoCommand):
    """Apply / restore a list of photo snapshots (matched by id)."""

    def __init__(
        self,
        project_id: str,
        before: list[PhotoRecord],
        after: list[PhotoRecord],
        text: str = "Update photos",
        *,
        on_applied: Callable[[list[PhotoRecord]], None] | None = None,
        parent: QUndoCommand | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._project_id = project_id
        self._before = copy_photos(before)
        self._after = copy_photos(after)
        self._on_applied = on_applied

    def redo(self) -> None:
        self._apply(self._after)

    def undo(self) -> None:
        self._apply(self._before)

    def _apply(self, photos: list[PhotoRecord]) -> None:
        repo = PhotoRepository(self._project_id)
        saved: list[PhotoRecord] = []
        for photo in photos:
            saved.append(repo.upsert(photo))
        if self._on_applied is not None:
            self._on_applied(saved)
