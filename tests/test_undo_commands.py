"""Tests for undo/redo project-edit commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from src.commands import (
    BulkPhotosSnapshotCommand,
    PhotoSnapshotCommand,
    copy_photo,
    copy_photos,
)
from src.database.photo_repository import PhotoRepository
from src.database.repository import ProjectRepository
from src.domain.models import (
    LifeStage,
    PhotoRecord,
    ProjectConfig,
    ReferencePhoto,
    ReviewStatus,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def project_env(tmp_path: Path, monkeypatch):
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    index_path = tmp_path / "app_index.db"

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

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    output_dir.mkdir()

    ref_path = input_dir / "ref.jpg"
    Image.new("RGB", (32, 32), color=(255, 0, 0)).save(ref_path)

    project = ProjectConfig(
        name="Undo Test",
        input_folder=input_dir,
        output_folder=output_dir,
        reference_photos=[
            ReferencePhoto(file_path=ref_path, life_stage=LifeStage.UNKNOWN)
        ],
    )
    ProjectRepository().create(project)
    return project, input_dir


def _add_photo(project_id: str, path: Path, **kwargs) -> PhotoRecord:
    record = PhotoRecord(
        project_id=project_id,
        original_path=path,
        review_status=kwargs.pop("review_status", ReviewStatus.NEEDS_REVIEW),
        **kwargs,
    )
    return PhotoRepository(project_id).upsert(record)


def test_exclude_undo_redo_restores_status(project_env, qapp) -> None:
    project, input_dir = project_env
    photo_path = input_dir / "scan.jpg"
    Image.new("RGB", (16, 16), color=(0, 128, 255)).save(photo_path)
    photo = _add_photo(project.id, photo_path, review_status=ReviewStatus.APPROVED)

    stack = QUndoStack()
    before = copy_photo(photo)
    after = copy_photo(photo)
    after.review_status = ReviewStatus.EXCLUDED
    stack.push(
        PhotoSnapshotCommand(
            project.id,
            before,
            after,
            "Remove from project",
        )
    )

    repo = PhotoRepository(project.id)
    loaded = next(p for p in repo.list_photos() if p.id == photo.id)
    assert loaded.review_status == ReviewStatus.EXCLUDED

    stack.undo()
    loaded = next(p for p in repo.list_photos() if p.id == photo.id)
    assert loaded.review_status == ReviewStatus.APPROVED

    stack.redo()
    loaded = next(p for p in repo.list_photos() if p.id == photo.id)
    assert loaded.review_status == ReviewStatus.EXCLUDED


def test_bulk_order_snapshot_round_trip(project_env, qapp) -> None:
    project, input_dir = project_env
    photos: list[PhotoRecord] = []
    for index in range(3):
        path = input_dir / f"p{index}.jpg"
        Image.new("RGB", (8, 8), color=(index * 40, 10, 10)).save(path)
        photos.append(
            _add_photo(
                project.id,
                path,
                sort_score=float(index),
                manual_order=index,
            )
        )

    before = copy_photos(photos)
    after = copy_photos(list(reversed(photos)))
    for index, photo in enumerate(after):
        photo.manual_order = index
        photo.sort_score = float(index)

    stack = QUndoStack()
    stack.push(
        BulkPhotosSnapshotCommand(
            project.id,
            before,
            after,
            "Save custom order",
        )
    )

    repo = PhotoRepository(project.id)
    by_id = {p.id: p for p in repo.list_photos()}
    for index, original in enumerate(reversed(photos)):
        assert by_id[original.id].manual_order == index
        assert by_id[original.id].sort_score == float(index)

    stack.undo()
    by_id = {p.id: p for p in repo.list_photos()}
    for index, original in enumerate(photos):
        assert by_id[original.id].manual_order == index
        assert by_id[original.id].sort_score == float(index)

    stack.redo()
    by_id = {p.id: p for p in repo.list_photos()}
    for index, original in enumerate(reversed(photos)):
        assert by_id[original.id].manual_order == index


def test_stack_clear_drops_history(project_env, qapp) -> None:
    project, input_dir = project_env
    photo_path = input_dir / "clear.jpg"
    Image.new("RGB", (16, 16), color=(20, 20, 20)).save(photo_path)
    photo = _add_photo(project.id, photo_path)

    stack = QUndoStack()
    before = copy_photo(photo)
    after = copy_photo(photo)
    after.review_status = ReviewStatus.EXCLUDED
    stack.push(PhotoSnapshotCommand(project.id, before, after, "Exclude"))
    assert stack.canUndo()
    stack.clear()
    assert not stack.canUndo()
    assert not stack.canRedo()
