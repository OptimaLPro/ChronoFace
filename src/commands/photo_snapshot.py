"""Undo command that restores a single photo row."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QUndoCommand

from src.commands.snapshots import copy_photo
from src.database.photo_repository import PhotoRepository
from src.domain.models import PhotoRecord


class PhotoSnapshotCommand(QUndoCommand):
    """Apply / restore a before→after PhotoRecord snapshot."""

    def __init__(
        self,
        project_id: str,
        before: PhotoRecord,
        after: PhotoRecord,
        text: str = "Edit photo",
        *,
        on_applied: Callable[[PhotoRecord], None] | None = None,
        parent: QUndoCommand | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._project_id = project_id
        self._before = copy_photo(before)
        self._after = copy_photo(after)
        self._on_applied = on_applied

    def redo(self) -> None:
        self._apply(self._after)

    def undo(self) -> None:
        self._apply(self._before)

    def _apply(self, photo: PhotoRecord) -> None:
        saved = PhotoRepository(self._project_id).upsert(copy_photo(photo))
        if self._on_applied is not None:
            self._on_applied(saved)
