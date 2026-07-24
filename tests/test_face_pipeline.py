"""Tests for face analysis pipeline with injectable mocks."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from src.database.photo_repository import PhotoRepository
from src.database.repository import ProjectRepository
from src.domain.models import LifeStage, ProjectConfig, ReferencePhoto, ReviewStatus
from src.vision.interfaces import DetectedFace, FaceDetector, FaceRecognizer
from src.workers.face_pipeline import FaceAnalysisPipeline, FacePipelineConfig
from src.workers.metadata_pipeline import MetadataPipeline, MetadataPipelineConfig


class FakeDetector(FaceDetector):
    def __init__(self, faces_by_name: dict[str, list[DetectedFace]]) -> None:
        self.faces_by_name = faces_by_name

    def detect(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        # Tests call detect_path indirectly via pipeline reading path names;
        # the fake embedder/pipeline uses path-based setup instead.
        return []


class PathAwareFakeDetector(FaceDetector):
    def __init__(self, mapping: dict[str, list[DetectedFace]]) -> None:
        self.mapping = mapping
        self._current_name = ""

    def set_current_name(self, name: str) -> None:
        self._current_name = name

    def detect(self, image_bgr: np.ndarray) -> list[DetectedFace]:
        return list(self.mapping.get(self._current_name, []))


class FakeEmbedder(FaceRecognizer):
    def align_and_embed(self, image_bgr: np.ndarray, face: DetectedFace) -> DetectedFace:
        embedding = face.embedding
        if embedding is None:
            embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        return DetectedFace(
            bbox_x=face.bbox_x,
            bbox_y=face.bbox_y,
            bbox_w=face.bbox_w,
            bbox_h=face.bbox_h,
            detection_score=face.detection_score,
            landmarks=face.landmarks,
            aligned_bgr=np.zeros((112, 112, 3), dtype=np.uint8),
            embedding=np.asarray(embedding, dtype=np.float32),
            quality_score=face.quality_score,
        )

    def create_embedding(self, image_path: Path) -> list[float]:
        return [1.0, 0.0, 0.0]


class FakeAgeEstimator:
    def estimate_age(self, face_image):
        return 8.0, 0.6


def test_face_pipeline_matches_target(tmp_path: Path, monkeypatch) -> None:
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
        "src.database.repository.recent_projects_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "src.workers.metadata_pipeline.project_cache_dir",
        lambda project_id: cache_root / project_id,
    )
    monkeypatch.setattr(
        "src.workers.face_pipeline.project_cache_dir",
        lambda project_id: cache_root / project_id,
    )
    monkeypatch.setattr(
        "src.settings.app_settings.app_data_dir",
        lambda: tmp_path / "appdata",
    )

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    ref = input_dir / "ref.jpg"
    target = input_dir / "group.jpg"
    other = input_dir / "stranger.jpg"
    Image.new("RGB", (64, 64), color=(255, 0, 0)).save(ref)
    Image.new("RGB", (64, 64), color=(0, 255, 0)).save(target)
    Image.new("RGB", (64, 64), color=(0, 0, 255)).save(other)

    target_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    other_vec = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    mapping = {
        "ref.jpg": [
            DetectedFace(
                bbox_x=1,
                bbox_y=1,
                bbox_w=20,
                bbox_h=20,
                detection_score=0.99,
                embedding=target_vec,
            )
        ],
        "group.jpg": [
            DetectedFace(
                bbox_x=1,
                bbox_y=1,
                bbox_w=50,
                bbox_h=50,
                detection_score=0.95,
                embedding=other_vec,
            ),
            DetectedFace(
                bbox_x=5,
                bbox_y=5,
                bbox_w=15,
                bbox_h=15,
                detection_score=0.80,
                embedding=target_vec,
            ),
        ],
        "stranger.jpg": [
            DetectedFace(
                bbox_x=1,
                bbox_y=1,
                bbox_w=20,
                bbox_h=20,
                detection_score=0.90,
                embedding=other_vec,
            )
        ],
    }

    detector = PathAwareFakeDetector(mapping)
    embedder = FakeEmbedder()

    from src.utils import image_utils

    original_read = image_utils.read_image_bgr

    def fake_read(path, *args, **kwargs):
        name = Path(path).name
        detector.set_current_name(name)
        return original_read(path)

    monkeypatch.setattr("src.utils.image_utils.read_image_bgr", fake_read)
    # face_pipeline imports read_image_bgr inside methods; patch the source module.
    monkeypatch.setattr(
        "src.workers.face_pipeline.read_image_bgr",
        fake_read,
        raising=False,
    )

    config = ProjectConfig(
        name="Face Test",
        input_folder=input_dir,
        output_folder=output_dir,
        reference_photos=[
            ReferencePhoto(file_path=ref, life_stage=LifeStage.CHILDHOOD)
        ],
    )
    saved = ProjectRepository().create(config)

    MetadataPipeline(
        MetadataPipelineConfig(project_id=saved.id, input_folder=input_dir)
    ).run()

    summary = FaceAnalysisPipeline(
        FacePipelineConfig(
            project_id=saved.id,
            reference_photos=saved.reference_photos,
        ),
        detector=detector,
        embedder=embedder,
        age_estimator=FakeAgeEstimator(),
    ).run()

    assert summary.reference_embeddings == 1
    assert summary.target_found >= 1
    assert summary.target_not_found >= 1

    photos = {p.original_path.name: p for p in PhotoRepository(saved.id).list_photos()}
    assert photos["group.jpg"].target_found is True
    assert photos["group.jpg"].review_status == ReviewStatus.NEEDS_REVIEW
    assert photos["stranger.jpg"].target_found is False
    assert photos["stranger.jpg"].review_status in {
        ReviewStatus.TARGET_NOT_FOUND,
        ReviewStatus.LOW_CONFIDENCE,
    }
