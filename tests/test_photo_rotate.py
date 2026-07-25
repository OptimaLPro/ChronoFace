"""Project photo rotate keeps analysis and remaps face boxes."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.database.face_repository import FaceRecord, FaceRepository
from src.database.photo_repository import PhotoRepository
from src.database.repository import ProjectRepository
from src.domain.models import (
    LifeStage,
    PhotoRecord,
    ProjectConfig,
    ReferencePhoto,
    ReviewStatus,
)
from src.utils.lossless_rotate import RotateDirection
from src.utils.photo_rotate import rotate_project_photo, transform_bbox_after_rotate


def test_transform_bbox_right_and_left() -> None:
    # Image 100x50, box at (10, 5, 20, 10)
    x, y, w, h = transform_bbox_after_rotate(
        10, 5, 20, 10, image_width=100, image_height=50, direction=RotateDirection.RIGHT
    )
    assert (x, y, w, h) == (50 - 5 - 10, 10, 10, 20)
    # Left undoes right
    x2, y2, w2, h2 = transform_bbox_after_rotate(
        x, y, w, h, image_width=50, image_height=100, direction=RotateDirection.LEFT
    )
    assert (x2, y2, w2, h2) == (10, 5, 20, 10)


def test_rotate_project_photo_keeps_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    index_path = tmp_path / "app_index.db"
    cache_root = tmp_path / "cache"

    def _db_path(project_id: str) -> Path:
        path = projects_root / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path / "project.db"

    monkeypatch.setattr("src.database.repository.project_db_path", _db_path)
    monkeypatch.setattr("src.database.photo_repository.project_db_path", _db_path)
    monkeypatch.setattr("src.database.face_repository.project_db_path", _db_path)
    monkeypatch.setattr(
        "src.database.repository.recent_projects_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "src.utils.photo_rotate.project_cache_dir",
        lambda project_id: (cache_root / project_id),
    )

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()
    ref = input_dir / "ref.jpg"
    Image.new("RGB", (32, 32), color=(255, 0, 0)).save(ref)

    project = ProjectRepository().create(
        ProjectConfig(
            name="Rotate Test",
            input_folder=input_dir,
            output_folder=output_dir,
            reference_photos=[
                ReferencePhoto(file_path=ref, life_stage=LifeStage.UNKNOWN)
            ],
        )
    )

    photo_path = input_dir / "kid.jpg"
    Image.new("RGB", (64, 48), color=(20, 40, 60)).save(
        photo_path, format="JPEG", quality=90
    )

    photo = PhotoRepository(project.id).upsert(
        PhotoRecord(
            project_id=project.id,
            original_path=photo_path,
            target_found=True,
            identity_score=0.9,
            estimated_age=3.0,
            age_confidence=0.8,
            face_quality=0.7,
            overall_confidence=0.85,
            review_status=ReviewStatus.APPROVED,
        )
    )
    assert photo.id is not None
    faces = FaceRepository(project.id).replace_faces_for_photo(
        photo.id,
        [
            FaceRecord(
                photo_id=photo.id,
                bbox_x=10,
                bbox_y=4,
                bbox_w=8,
                bbox_h=12,
                identity_score=0.9,
                estimated_age=3.0,
                is_selected_target=True,
            )
        ],
    )
    face_id = faces[0].id
    assert face_id is not None
    photo.selected_face_id = face_id
    photo = PhotoRepository(project.id).upsert(photo)

    updated = rotate_project_photo(project.id, photo, RotateDirection.RIGHT)
    with Image.open(photo_path) as image:
        assert image.size == (48, 64)

    assert updated.target_found is True
    assert updated.identity_score == 0.9
    assert updated.estimated_age == 3.0
    assert updated.review_status == ReviewStatus.APPROVED
    assert updated.selected_face_id == face_id

    faces_after = FaceRepository(project.id).list_faces_for_photo(photo.id)
    assert len(faces_after) == 1
    face = faces_after[0]
    assert face.id == face_id
    # CW on 64x48: (10,4,8,12) -> (48-4-12, 10, 12, 8) = (32, 10, 12, 8)
    assert face.bbox_x == 32
    assert face.bbox_y == 10
    assert face.bbox_w == 12
    assert face.bbox_h == 8
    assert face.identity_score == 0.9
    assert face.is_selected_target is True
