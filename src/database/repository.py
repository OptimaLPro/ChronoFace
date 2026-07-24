"""Persistence layer for projects and the recent-projects index."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.database.migrations import initialize_app_index, initialize_database
from src.domain.models import LifeStage, ProjectConfig, ReferencePhoto
from src.utils.logging import get_logger
from src.utils.paths import project_db_path, recent_projects_index_path

logger = get_logger("database.repository")


def _parse_optional_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


class ProjectRepository:
    """Create, load, and update project SQLite databases."""

    def create(self, config: ProjectConfig) -> ProjectConfig:
        """Persist a new project and register it in the recent-projects index."""
        self._validate(config)
        now = datetime.now().isoformat(timespec="seconds")
        config.created_at = _parse_datetime(now)
        config.updated_at = config.created_at

        db_path = project_db_path(config.id)
        connection = initialize_database(db_path)
        try:
            connection.execute(
                """
                INSERT INTO project (
                    id, name, input_folder, output_folder, date_of_birth,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    config.id,
                    config.name.strip(),
                    str(config.input_folder.resolve()),
                    str(config.output_folder.resolve()),
                    config.date_of_birth.isoformat() if config.date_of_birth else None,
                    now,
                    now,
                ),
            )
            self._replace_references(connection, config)
            connection.commit()
        finally:
            connection.close()

        self._touch_recent(config, db_path)
        logger.info("Created project '%s' (%s)", config.name, config.id)
        return config

    def update(self, config: ProjectConfig) -> ProjectConfig:
        """Update project settings and reference photos."""
        self._validate(config)
        now = datetime.now().isoformat(timespec="seconds")
        config.updated_at = _parse_datetime(now)

        db_path = project_db_path(config.id)
        connection = initialize_database(db_path)
        try:
            connection.execute(
                """
                UPDATE project
                SET name = ?,
                    input_folder = ?,
                    output_folder = ?,
                    date_of_birth = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    config.name.strip(),
                    str(config.input_folder.resolve()),
                    str(config.output_folder.resolve()),
                    config.date_of_birth.isoformat() if config.date_of_birth else None,
                    now,
                    config.id,
                ),
            )
            connection.execute(
                "DELETE FROM reference_photos WHERE project_id = ?",
                (config.id,),
            )
            self._replace_references(connection, config)
            connection.commit()
        finally:
            connection.close()

        self._touch_recent(config, db_path)
        logger.info("Updated project '%s' (%s)", config.name, config.id)
        return config

    def load(self, project_id: str) -> ProjectConfig:
        """Load a project by id."""
        db_path = project_db_path(project_id)
        if not db_path.exists():
            raise FileNotFoundError(f"Project database not found: {db_path}")

        connection = initialize_database(db_path)
        try:
            row = connection.execute(
                "SELECT * FROM project WHERE id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError(f"Project record missing in {db_path}")

            references = []
            for ref in connection.execute(
                """
                SELECT id, file_path, life_stage, sort_order
                FROM reference_photos
                WHERE project_id = ?
                ORDER BY sort_order ASC, id ASC
                """,
                (project_id,),
            ):
                references.append(
                    ReferencePhoto(
                        id=ref["id"],
                        file_path=Path(ref["file_path"]),
                        life_stage=LifeStage(ref["life_stage"]),
                        sort_order=ref["sort_order"],
                    )
                )

            config = ProjectConfig(
                id=row["id"],
                name=row["name"],
                input_folder=Path(row["input_folder"]),
                output_folder=Path(row["output_folder"]),
                date_of_birth=_parse_optional_date(row["date_of_birth"]),
                reference_photos=references,
                created_at=_parse_datetime(row["created_at"]),
                updated_at=_parse_datetime(row["updated_at"]),
            )
        finally:
            connection.close()

        self._touch_recent(config, db_path)
        return config

    def list_recent(self, limit: int = 20) -> list[dict]:
        """Return recent projects for the Open / welcome UI."""
        connection = initialize_app_index(recent_projects_index_path())
        try:
            rows = connection.execute(
                """
                SELECT id, name, db_path, input_folder, output_folder, last_opened_at
                FROM recent_projects
                ORDER BY last_opened_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def _replace_references(self, connection, config: ProjectConfig) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        for index, reference in enumerate(config.reference_photos):
            connection.execute(
                """
                INSERT INTO reference_photos (
                    project_id, file_path, life_stage, sort_order, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    config.id,
                    str(Path(reference.file_path).resolve()),
                    reference.life_stage.value,
                    reference.sort_order if reference.sort_order else index,
                    now,
                ),
            )

    def _touch_recent(self, config: ProjectConfig, db_path: Path) -> None:
        connection = initialize_app_index(recent_projects_index_path())
        try:
            connection.execute(
                """
                INSERT INTO recent_projects (
                    id, name, db_path, input_folder, output_folder, last_opened_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    db_path = excluded.db_path,
                    input_folder = excluded.input_folder,
                    output_folder = excluded.output_folder,
                    last_opened_at = excluded.last_opened_at
                """,
                (
                    config.id,
                    config.name.strip(),
                    str(db_path),
                    str(config.input_folder.resolve()),
                    str(config.output_folder.resolve()),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _validate(self, config: ProjectConfig) -> None:
        if not config.name or not config.name.strip():
            raise ValueError("Project name is required.")
        if not config.input_folder or not Path(config.input_folder).is_dir():
            raise ValueError("Input folder must be an existing directory.")
        if not config.output_folder:
            raise ValueError("Output folder is required.")

        input_resolved = Path(config.input_folder).resolve()
        output_resolved = Path(config.output_folder).resolve()
        if input_resolved == output_resolved:
            raise ValueError("Output folder must be different from the input folder.")

        output_resolved.mkdir(parents=True, exist_ok=True)

        if not config.reference_photos:
            raise ValueError("Select at least one reference photo.")

        for reference in config.reference_photos:
            path = Path(reference.file_path)
            if not path.is_file():
                raise ValueError(f"Reference photo not found: {path}")
