"""Tests for Phase 2 metadata pipeline and photo persistence."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import piexif
from PIL import Image

from src.database.photo_repository import PhotoRepository
from src.database.repository import ProjectRepository
from src.domain.models import (
    DateReliability,
    LifeStage,
    ProjectConfig,
    ReferencePhoto,
)
from src.workers.metadata_pipeline import MetadataPipeline, MetadataPipelineConfig


def _write_jpeg_with_exif(path: Path, when: datetime) -> None:
    image = Image.new("RGB", (64, 64), color=(80, 120, 160))
    exif_dict = {
        "0th": {},
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: when.strftime("%Y:%m:%d %H:%M:%S").encode()
        },
        "1st": {},
        "thumbnail": None,
        "GPS": {},
    }
    image.save(path, format="JPEG", exif=piexif.dump(exif_dict))


def test_metadata_pipeline_processes_and_skips(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    monkeypatch.setattr(
        "src.database.repository.recent_projects_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "src.workers.metadata_pipeline.project_cache_dir",
        lambda project_id: (cache_root / project_id),
    )

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    ref = input_dir / "ref.jpg"
    Image.new("RGB", (32, 32), color=(255, 0, 0)).save(ref)

    photo_a = input_dir / "child_2016.jpg"
    _write_jpeg_with_exif(photo_a, datetime(2016, 4, 1, 10, 0, 0))
    photo_b = input_dir / "plain.png"
    Image.new("RGB", (40, 40), color=(0, 255, 0)).save(photo_b)

    config = ProjectConfig(
        name="Pipeline Test",
        input_folder=input_dir,
        output_folder=output_dir,
        date_of_birth=date(2010, 1, 1),
        reference_photos=[
            ReferencePhoto(file_path=ref, life_stage=LifeStage.CHILDHOOD)
        ],
    )
    saved = ProjectRepository().create(config)

    pipeline = MetadataPipeline(
        MetadataPipelineConfig(
            project_id=saved.id,
            input_folder=input_dir,
            date_of_birth=date(2010, 1, 1),
        )
    )
    summary = pipeline.run()
    assert summary.total_discovered == 3  # ref + 2 photos
    assert summary.processed == 3
    assert summary.errors == 0
    assert summary.with_reliable_date >= 1

    repo = PhotoRepository(saved.id)
    records = repo.list_photos()
    assert len(records) == 3

    child = next(r for r in records if r.original_path.name == "child_2016.jpg")
    assert child.date_reliability == DateReliability.RELIABLE_EXIF
    assert child.age_from_dob is not None
    assert 5.0 < child.age_from_dob < 7.0
    assert child.filename_year == 2016
    assert child.thumbnail_path is not None
    assert Path(child.thumbnail_path).is_file()
    assert child.file_hash

    # Second run should skip unchanged files.
    summary2 = pipeline.run()
    assert summary2.skipped_unchanged == 3
    assert summary2.processed == 0
