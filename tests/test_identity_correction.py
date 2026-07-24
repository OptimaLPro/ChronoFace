"""Tests for the identity correction service (face reassignment)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
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
from src.services.identity_correction import IdentityCorrectionService


class StubAgeEstimator:
    def __init__(self, age: float = 12.5, confidence: float = 0.7) -> None:
        self.age = age
        self.confidence = confidence
        self.calls = 0

    def estimate_age(self, face_image: np.ndarray) -> tuple[float, float]:
        self.calls += 1
        return self.age, self.confidence


@pytest.fixture()
def project_env(tmp_path: Path, monkeypatch):
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    index_path = tmp_path / "app_index.db"
    cache_root = tmp_path / "cache"
    cache_root.mkdir()

    def _db_path(project_id: str) -> Path:
        path = projects_root / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path / "project.db"

    monkeypatch.setattr("src.database.repository.project_db_path", _db_path)
    monkeypatch.setattr("src.database.photo_repository.project_db_path", _db_path)
    monkeypatch.setattr("src.database.face_repository.project_db_path", _db_path)
    monkeypatch.setattr(
        "src.database.repository.recent_projects_index_path", lambda: index_path
    )
    monkeypatch.setattr(
        "src.services.identity_correction.project_cache_dir",
        lambda project_id: cache_root / project_id,
    )

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()

    ref_path = input_dir / "ref.jpg"
    Image.new("RGB", (32, 32), color=(255, 0, 0)).save(ref_path)

    project = ProjectConfig(
        name="Test",
        input_folder=input_dir,
        output_folder=output_dir,
        reference_photos=[
            ReferencePhoto(file_path=ref_path, life_stage=LifeStage.UNKNOWN)
        ],
    )
    ProjectRepository().create(project)
    return project, tmp_path


def _save_face_crop(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), color=(200, 200, 200)).save(path)
    return path


def test_reassign_target_face_updates_photo_and_faces(project_env, tmp_path: Path) -> None:
    project, _root = project_env

    photo_path = project.input_folder / "group.jpg"
    Image.new("RGB", (64, 64), color=(0, 255, 0)).save(photo_path)

    photo_repo = PhotoRepository(project.id)
    photo = PhotoRepository(project.id).upsert(
        PhotoRecord(
            project_id=project.id,
            original_path=photo_path,
            target_found=True,
            identity_score=0.4,
            estimated_age=35.0,
            age_confidence=0.5,
            face_quality=0.6,
            review_status=ReviewStatus.LOW_CONFIDENCE,
        )
    )

    face_repo = FaceRepository(project.id)
    embed_a = tmp_path / "embed_a.npy"
    embed_b = tmp_path / "embed_b.npy"
    FaceRepository.save_embedding(embed_a, np.array([1.0, 0.0, 0.0], dtype=np.float32))
    FaceRepository.save_embedding(embed_b, np.array([0.0, 1.0, 0.0], dtype=np.float32))

    crop_a = _save_face_crop(tmp_path / "crops" / "a.jpg")
    crop_b = _save_face_crop(tmp_path / "crops" / "b.jpg")

    face_a = FaceRecord(
        photo_id=photo.id,
        bbox_x=0, bbox_y=0, bbox_w=32, bbox_h=32,
        embedding_path=str(embed_a),
        face_crop_path=str(crop_a),
        quality_score=0.5,
        identity_score=0.4,
        estimated_age=35.0,
        is_selected_target=True,
    )
    face_b = FaceRecord(
        photo_id=photo.id,
        bbox_x=40, bbox_y=0, bbox_w=32, bbox_h=32,
        embedding_path=str(embed_b),
        face_crop_path=str(crop_b),
        quality_score=0.8,
        identity_score=0.85,
        estimated_age=None,
        is_selected_target=False,
    )
    saved = face_repo.replace_faces_for_photo(photo.id, [face_a, face_b])
    target_face_id = saved[1].id

    stub = StubAgeEstimator(age=9.5, confidence=0.8)
    service = IdentityCorrectionService(
        project.id, age_estimator=stub
    )
    result = service.reassign_target_face(
        photo,
        target_face_id,
        also_add_as_reference=True,
        reference_life_stage=LifeStage.CHILDHOOD,
    )

    assert stub.calls == 1
    assert result.face.id == target_face_id
    assert result.face.is_selected_target is True
    assert result.face.estimated_age == pytest.approx(9.5)

    faces_after = face_repo.list_faces_for_photo(photo.id)
    selected = [f for f in faces_after if f.is_selected_target]
    assert len(selected) == 1
    assert selected[0].id == target_face_id

    reloaded = photo_repo.get_by_path(photo.original_path)
    assert reloaded is not None
    assert reloaded.selected_face_id == target_face_id
    assert reloaded.target_found is True
    assert reloaded.identity_score == pytest.approx(0.85)
    assert reloaded.face_quality == pytest.approx(0.8)
    assert reloaded.estimated_age == pytest.approx(9.5)
    assert reloaded.age_confidence == pytest.approx(0.8)
    assert reloaded.review_status == ReviewStatus.MANUALLY_CORRECTED

    assert face_repo.count_reference_embeddings() == 1


def test_reassign_uses_existing_face_age_without_reestimate(
    project_env, tmp_path: Path
) -> None:
    """Switching target must adopt that face's own stored age."""
    project, _root = project_env

    photo_path = project.input_folder / "pair.jpg"
    Image.new("RGB", (64, 64), color=(0, 128, 255)).save(photo_path)
    photo = PhotoRepository(project.id).upsert(
        PhotoRecord(
            project_id=project.id,
            original_path=photo_path,
            target_found=True,
            identity_score=0.9,
            estimated_age=14.0,
            review_status=ReviewStatus.NEEDS_REVIEW,
        )
    )

    face_repo = FaceRepository(project.id)
    embed_a = tmp_path / "a.npy"
    embed_b = tmp_path / "b.npy"
    FaceRepository.save_embedding(embed_a, np.array([1.0, 0.0], dtype=np.float32))
    FaceRepository.save_embedding(embed_b, np.array([0.0, 1.0], dtype=np.float32))
    crop_a = _save_face_crop(tmp_path / "crops" / "child.jpg")
    crop_b = _save_face_crop(tmp_path / "crops" / "adult.jpg")

    saved = face_repo.replace_faces_for_photo(
        photo.id,
        [
            FaceRecord(
                photo_id=photo.id,
                bbox_x=0, bbox_y=0, bbox_w=20, bbox_h=20,
                embedding_path=str(embed_a),
                face_crop_path=str(crop_a),
                identity_score=0.9,
                estimated_age=14.0,
                is_selected_target=True,
            ),
            FaceRecord(
                photo_id=photo.id,
                bbox_x=30, bbox_y=0, bbox_w=20, bbox_h=20,
                embedding_path=str(embed_b),
                face_crop_path=str(crop_b),
                identity_score=0.1,
                estimated_age=52.0,
                is_selected_target=False,
            ),
        ],
    )
    adult_id = saved[1].id

    stub = StubAgeEstimator(age=99.0, confidence=0.9)
    service = IdentityCorrectionService(project.id, age_estimator=stub)
    result = service.reassign_target_face(
        photo,
        adult_id,
        also_add_as_reference=False,
    )

    assert stub.calls == 0
    assert result.face.estimated_age == pytest.approx(52.0)
    assert result.photo.estimated_age == pytest.approx(52.0)

    faces_after = face_repo.list_faces_for_photo(photo.id)
    by_id = {face.id: face for face in faces_after}
    assert by_id[saved[0].id].estimated_age == pytest.approx(14.0)
    assert by_id[adult_id].estimated_age == pytest.approx(52.0)
    assert by_id[adult_id].is_selected_target is True


def test_reassign_rejects_face_from_other_photo(project_env, tmp_path: Path) -> None:
    project, _root = project_env

    p1 = project.input_folder / "one.jpg"
    p2 = project.input_folder / "two.jpg"
    Image.new("RGB", (32, 32), color=(1, 2, 3)).save(p1)
    Image.new("RGB", (32, 32), color=(4, 5, 6)).save(p2)

    photo_repo = PhotoRepository(project.id)
    photo1 = photo_repo.upsert(PhotoRecord(project_id=project.id, original_path=p1))
    photo2 = photo_repo.upsert(PhotoRecord(project_id=project.id, original_path=p2))

    face_repo = FaceRepository(project.id)
    embed = tmp_path / "e.npy"
    FaceRepository.save_embedding(embed, np.array([1.0], dtype=np.float32))
    face_for_photo2 = face_repo.replace_faces_for_photo(
        photo2.id,
        [
            FaceRecord(
                photo_id=photo2.id,
                bbox_x=0, bbox_y=0, bbox_w=8, bbox_h=8,
                embedding_path=str(embed),
                is_selected_target=True,
            )
        ],
    )[0]

    service = IdentityCorrectionService(
        project.id, age_estimator=StubAgeEstimator()
    )

    with pytest.raises(ValueError):
        service.reassign_target_face(photo1, face_for_photo2.id)
