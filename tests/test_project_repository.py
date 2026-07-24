"""Phase 1 tests for project persistence."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.database.repository import ProjectRepository
from src.domain.models import LifeStage, ProjectConfig, ReferencePhoto


@pytest.fixture()
def sample_image(tmp_path: Path) -> Path:
    image = tmp_path / "ref.jpg"
    # Minimal JPEG-like bytes are not required; repository only checks is_file().
    image.write_bytes(b"fake-image-bytes")
    return image


def test_create_and_reload_project(tmp_path: Path, sample_image: Path, monkeypatch) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    index_path = tmp_path / "app_index.db"

    def _db_path(project_id: str) -> Path:
        return projects_root / project_id / "project.db"

    monkeypatch.setattr("src.database.repository.project_db_path", _db_path)
    monkeypatch.setattr(
        "src.database.repository.recent_projects_index_path",
        lambda: index_path,
    )

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()

    config = ProjectConfig(
        name="Test Event",
        input_folder=input_dir,
        output_folder=output_dir,
        date_of_birth=date(2012, 5, 1),
        reference_photos=[
            ReferencePhoto(file_path=sample_image, life_stage=LifeStage.CHILDHOOD)
        ],
    )

    repo = ProjectRepository()
    saved = repo.create(config)
    loaded = repo.load(saved.id)

    assert loaded.name == "Test Event"
    assert loaded.date_of_birth == date(2012, 5, 1)
    assert len(loaded.reference_photos) == 1
    assert loaded.reference_photos[0].life_stage == LifeStage.CHILDHOOD
    assert loaded.input_folder.resolve() == input_dir.resolve()
    assert loaded.include_subfolders is True

    loaded.include_subfolders = False
    repo.update(loaded)
    reloaded = repo.load(saved.id)
    assert reloaded.include_subfolders is False

    recent = repo.list_recent()
    assert any(item["id"] == saved.id for item in recent)


def test_delete_project_removes_data_keeps_photos(
    tmp_path: Path, sample_image: Path, monkeypatch
) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    index_path = tmp_path / "app_index.db"

    def _db_path(project_id: str) -> Path:
        return projects_root / project_id / "project.db"

    monkeypatch.setattr("src.database.repository.project_db_path", _db_path)
    monkeypatch.setattr(
        "src.database.repository.projects_dir",
        lambda: projects_root,
    )
    monkeypatch.setattr(
        "src.database.repository.recent_projects_index_path",
        lambda: index_path,
    )

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    photo = input_dir / "keep_me.jpg"
    photo.write_bytes(b"original-photo")

    config = ProjectConfig(
        name="Delete Me",
        input_folder=input_dir,
        output_folder=output_dir,
        reference_photos=[
            ReferencePhoto(file_path=sample_image, life_stage=LifeStage.CHILDHOOD)
        ],
    )

    repo = ProjectRepository()
    saved = repo.create(config)
    project_root = projects_root / saved.id
    cache_file = project_root / "cache" / "thumb.bin"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b"cache")

    repo.delete(saved.id)

    assert not project_root.exists()
    assert photo.exists()
    assert sample_image.exists()
    assert all(item["id"] != saved.id for item in repo.list_recent())
