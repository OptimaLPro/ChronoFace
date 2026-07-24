"""Persistence for detected faces and reference embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from src.database.migrations import initialize_database
from src.domain.models import LifeStage
from src.utils.logging import get_logger
from src.utils.paths import project_db_path

logger = get_logger("database.face_repository")


@dataclass
class FaceRecord:
    photo_id: int
    bbox_x: float
    bbox_y: float
    bbox_w: float
    bbox_h: float
    embedding_path: str | None = None
    face_crop_path: str | None = None
    quality_score: float | None = None
    identity_score: float | None = None
    estimated_age: float | None = None
    is_selected_target: bool = False
    id: int | None = None
    created_at: datetime | None = None


class FaceRepository:
    """CRUD for faces and reference embeddings within a project database."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.db_path = project_db_path(project_id)

    def replace_faces_for_photo(self, photo_id: int, faces: list[FaceRecord]) -> list[FaceRecord]:
        connection = initialize_database(self.db_path)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            connection.execute("DELETE FROM faces WHERE photo_id = ?", (photo_id,))
            saved: list[FaceRecord] = []
            for face in faces:
                cursor = connection.execute(
                    """
                    INSERT INTO faces (
                        photo_id, bbox_x, bbox_y, bbox_w, bbox_h,
                        embedding_path, face_crop_path, quality_score,
                        identity_score, estimated_age, is_selected_target, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        photo_id,
                        face.bbox_x,
                        face.bbox_y,
                        face.bbox_w,
                        face.bbox_h,
                        face.embedding_path,
                        face.face_crop_path,
                        face.quality_score,
                        face.identity_score,
                        face.estimated_age,
                        1 if face.is_selected_target else 0,
                        now,
                    ),
                )
                face.id = int(cursor.lastrowid)
                face.created_at = datetime.fromisoformat(now)
                saved.append(face)
            connection.commit()
            return saved
        finally:
            connection.close()

    def list_faces_for_photo(self, photo_id: int) -> list[FaceRecord]:
        connection = initialize_database(self.db_path)
        try:
            rows = connection.execute(
                "SELECT * FROM faces WHERE photo_id = ? ORDER BY id ASC",
                (photo_id,),
            ).fetchall()
            return [self._row_to_face(row) for row in rows]
        finally:
            connection.close()

    def get_face(self, face_id: int) -> Optional[FaceRecord]:
        connection = initialize_database(self.db_path)
        try:
            row = connection.execute(
                "SELECT * FROM faces WHERE id = ?",
                (face_id,),
            ).fetchone()
            return self._row_to_face(row) if row else None
        finally:
            connection.close()

    def set_selected_face(
        self,
        photo_id: int,
        face_id: int,
        *,
        estimated_age: float | None = None,
    ) -> Optional[FaceRecord]:
        """Mark exactly one face as the selected target for a photo."""
        connection = initialize_database(self.db_path)
        try:
            connection.execute(
                "UPDATE faces SET is_selected_target = 0 WHERE photo_id = ?",
                (photo_id,),
            )
            if estimated_age is not None:
                connection.execute(
                    "UPDATE faces SET is_selected_target = 1, estimated_age = ? WHERE id = ? AND photo_id = ?",
                    (float(estimated_age), face_id, photo_id),
                )
            else:
                connection.execute(
                    "UPDATE faces SET is_selected_target = 1 WHERE id = ? AND photo_id = ?",
                    (face_id, photo_id),
                )
            connection.commit()
        finally:
            connection.close()
        return self.get_face(face_id)

    def clear_reference_embeddings(self) -> None:
        connection = initialize_database(self.db_path)
        try:
            connection.execute(
                "DELETE FROM reference_embeddings WHERE project_id = ?",
                (self.project_id,),
            )
            connection.commit()
        finally:
            connection.close()

    def add_reference_embedding(
        self,
        *,
        source_path: Path,
        life_stage: LifeStage,
        embedding_path: Path,
        detection_score: float | None = None,
        reference_photo_id: int | None = None,
    ) -> int:
        connection = initialize_database(self.db_path)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            cursor = connection.execute(
                """
                INSERT INTO reference_embeddings (
                    project_id, reference_photo_id, source_path, life_stage,
                    embedding_path, detection_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.project_id,
                    reference_photo_id,
                    str(Path(source_path).resolve()),
                    life_stage.value,
                    str(embedding_path),
                    detection_score,
                    now,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)
        finally:
            connection.close()

    def count_reference_embeddings(self) -> int:
        connection = initialize_database(self.db_path)
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS c FROM reference_embeddings WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()
            return int(row["c"])
        finally:
            connection.close()

    @staticmethod
    def save_embedding(path: Path, embedding: np.ndarray) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(str(path), np.asarray(embedding, dtype=np.float32))
        return path

    @staticmethod
    def load_embedding(path: Path) -> np.ndarray:
        return np.load(str(path))

    def _row_to_face(self, row) -> FaceRecord:
        return FaceRecord(
            id=row["id"],
            photo_id=row["photo_id"],
            bbox_x=row["bbox_x"],
            bbox_y=row["bbox_y"],
            bbox_w=row["bbox_w"],
            bbox_h=row["bbox_h"],
            embedding_path=row["embedding_path"],
            face_crop_path=row["face_crop_path"],
            quality_score=row["quality_score"],
            identity_score=row["identity_score"],
            estimated_age=row["estimated_age"],
            is_selected_target=bool(row["is_selected_target"]),
            created_at=datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else None,
        )
