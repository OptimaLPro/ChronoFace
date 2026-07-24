"""Undo command for target-face reassignment (and optional reference promote)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QUndoCommand

from src.commands.snapshots import copy_photo
from src.database.face_repository import FaceRepository
from src.database.photo_repository import PhotoRepository
from src.domain.models import LifeStage, PhotoRecord
from src.services.identity_correction import IdentityCorrectionService


@dataclass(frozen=True)
class _FaceState:
    face_id: int
    is_selected_target: bool
    estimated_age: float | None


class FaceReassignCommand(QUndoCommand):
    """Reassign the selected face; undo restores photo + face selection state."""

    def __init__(
        self,
        project_id: str,
        photo: PhotoRecord,
        new_face_id: int,
        *,
        also_add_as_reference: bool = False,
        reference_life_stage: LifeStage = LifeStage.UNKNOWN,
        correction_service: IdentityCorrectionService,
        on_applied: Callable[[PhotoRecord], None] | None = None,
        parent: QUndoCommand | None = None,
    ) -> None:
        super().__init__("Reassign target face", parent)
        self._project_id = project_id
        self._photo_id = photo.id
        if self._photo_id is None:
            raise ValueError("Photo must be saved before reassigning faces")
        self._new_face_id = new_face_id
        self._also_add_as_reference = also_add_as_reference
        self._reference_life_stage = reference_life_stage
        self._service = correction_service
        self._on_applied = on_applied

        self._before_photo = copy_photo(photo)
        self._before_faces = self._snapshot_faces(self._photo_id)
        self._after_photo: PhotoRecord | None = None
        self._after_faces: list[_FaceState] | None = None
        self._ref_embedding_id: int | None = None
        self._ref_embedding_path: Path | None = None

    def redo(self) -> None:
        if self._after_photo is None:
            working = copy_photo(self._before_photo)
            result = self._service.reassign_target_face(
                working,
                self._new_face_id,
                also_add_as_reference=self._also_add_as_reference,
                reference_life_stage=self._reference_life_stage,
            )
            self._after_photo = copy_photo(result.photo)
            self._after_faces = self._snapshot_faces(self._photo_id)
            self._ref_embedding_id = result.reference_embedding_id
            self._ref_embedding_path = result.reference_embedding_path
            if self._on_applied is not None:
                self._on_applied(copy_photo(self._after_photo))
            return

        self._restore_photo(self._after_photo)
        assert self._after_faces is not None
        self._restore_faces(self._after_faces)
        if (
            self._ref_embedding_id is None
            and self._also_add_as_reference
            and self._ref_embedding_path is not None
            and self._ref_embedding_path.is_file()
        ):
            # First undo deleted the row; re-insert on subsequent redos.
            face_repo = FaceRepository(self._project_id)
            self._ref_embedding_id = face_repo.add_reference_embedding(
                source_path=self._after_photo.original_path,
                life_stage=self._reference_life_stage,
                embedding_path=self._ref_embedding_path,
            )
        if self._on_applied is not None:
            self._on_applied(copy_photo(self._after_photo))

    def undo(self) -> None:
        self._restore_photo(self._before_photo)
        self._restore_faces(self._before_faces)
        if self._ref_embedding_id is not None:
            FaceRepository(self._project_id).delete_reference_embedding(
                self._ref_embedding_id,
                delete_file=False,
            )
            self._ref_embedding_id = None
        if self._on_applied is not None:
            self._on_applied(copy_photo(self._before_photo))

    def _snapshot_faces(self, photo_id: int) -> list[_FaceState]:
        faces = FaceRepository(self._project_id).list_faces_for_photo(photo_id)
        return [
            _FaceState(
                face_id=face.id,
                is_selected_target=face.is_selected_target,
                estimated_age=face.estimated_age,
            )
            for face in faces
            if face.id is not None
        ]

    def _restore_photo(self, photo: PhotoRecord) -> None:
        PhotoRepository(self._project_id).upsert(copy_photo(photo))

    def _restore_faces(self, states: list[_FaceState]) -> None:
        FaceRepository(self._project_id).restore_face_states(
            self._photo_id,
            [
                (state.face_id, state.is_selected_target, state.estimated_age)
                for state in states
            ],
        )
