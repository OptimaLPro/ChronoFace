"""Undo command for project settings / reference list changes."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QUndoCommand

from src.commands.snapshots import copy_project
from src.database.repository import ProjectRepository
from src.domain.models import ProjectConfig


class ProjectConfigCommand(QUndoCommand):
    """Apply / restore a ProjectConfig snapshot."""

    def __init__(
        self,
        before: ProjectConfig,
        after: ProjectConfig,
        text: str = "Edit project",
        *,
        repository: ProjectRepository | None = None,
        on_applied: Callable[[ProjectConfig], None] | None = None,
        parent: QUndoCommand | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._before = copy_project(before)
        self._after = copy_project(after)
        self._repository = repository or ProjectRepository()
        self._on_applied = on_applied

    def redo(self) -> None:
        self._apply(self._after)

    def undo(self) -> None:
        self._apply(self._before)

    def _apply(self, config: ProjectConfig) -> None:
        saved = self._repository.update(copy_project(config))
        if self._on_applied is not None:
            self._on_applied(saved)
