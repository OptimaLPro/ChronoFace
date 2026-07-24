"""Persistence helpers for discovered / analyzed photos."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.database.migrations import initialize_database
from src.domain.models import DateReliability, PhotoRecord, ReviewStatus
from src.utils.logging import get_logger
from src.utils.paths import project_db_path

logger = get_logger("database.photo_repository")


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


class PhotoRepository:
    """CRUD for the photos table within a project database."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.db_path = project_db_path(project_id)

    def get_by_path(self, original_path: Path) -> Optional[PhotoRecord]:
        connection = initialize_database(self.db_path)
        try:
            row = connection.execute(
                """
                SELECT * FROM photos
                WHERE project_id = ? AND original_path = ?
                """,
                (self.project_id, str(Path(original_path).resolve())),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_record(row)
        finally:
            connection.close()

    def list_photos(self) -> list[PhotoRecord]:
        connection = initialize_database(self.db_path)
        try:
            rows = connection.execute(
                """
                SELECT * FROM photos
                WHERE project_id = ?
                ORDER BY
                    CASE WHEN sort_score IS NULL THEN 1 ELSE 0 END,
                    sort_score ASC,
                    CASE WHEN capture_date IS NULL THEN 1 ELSE 0 END,
                    capture_date ASC,
                    original_path ASC
                """,
                (self.project_id,),
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            connection.close()

    def count_photos(self) -> int:
        connection = initialize_database(self.db_path)
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS c FROM photos WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()
            return int(row["c"])
        finally:
            connection.close()

    def summarize(self) -> dict[str, int]:
        connection = initialize_database(self.db_path)
        try:
            total = connection.execute(
                "SELECT COUNT(*) AS c FROM photos WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()["c"]
            reliable = connection.execute(
                """
                SELECT COUNT(*) AS c FROM photos
                WHERE project_id = ? AND date_reliability = ?
                """,
                (self.project_id, DateReliability.RELIABLE_EXIF.value),
            ).fetchone()["c"]
            weak = connection.execute(
                """
                SELECT COUNT(*) AS c FROM photos
                WHERE project_id = ? AND date_reliability = ?
                """,
                (self.project_id, DateReliability.WEAK_FILESYSTEM.value),
            ).fetchone()["c"]
            none = connection.execute(
                """
                SELECT COUNT(*) AS c FROM photos
                WHERE project_id = ? AND date_reliability = ?
                """,
                (self.project_id, DateReliability.NONE.value),
            ).fetchone()["c"]
            errors = connection.execute(
                """
                SELECT COUNT(*) AS c FROM photos
                WHERE project_id = ? AND review_status = ?
                """,
                (self.project_id, ReviewStatus.ERROR.value),
            ).fetchone()["c"]
            target_found = connection.execute(
                """
                SELECT COUNT(*) AS c FROM photos
                WHERE project_id = ? AND target_found = 1
                """,
                (self.project_id,),
            ).fetchone()["c"]
            no_face = connection.execute(
                """
                SELECT COUNT(*) AS c FROM photos
                WHERE project_id = ? AND review_status = ?
                """,
                (self.project_id, ReviewStatus.NO_FACE.value),
            ).fetchone()["c"]
            not_found = connection.execute(
                """
                SELECT COUNT(*) AS c FROM photos
                WHERE project_id = ? AND review_status = ?
                """,
                (self.project_id, ReviewStatus.TARGET_NOT_FOUND.value),
            ).fetchone()["c"]
            low = connection.execute(
                """
                SELECT COUNT(*) AS c FROM photos
                WHERE project_id = ? AND review_status = ?
                """,
                (self.project_id, ReviewStatus.LOW_CONFIDENCE.value),
            ).fetchone()["c"]
            return {
                "total": int(total),
                "reliable_date": int(reliable),
                "weak_date": int(weak),
                "no_date": int(none),
                "errors": int(errors),
                "target_found": int(target_found),
                "no_face": int(no_face),
                "target_not_found": int(not_found),
                "low_confidence": int(low),
            }
        finally:
            connection.close()

    def upsert(self, record: PhotoRecord) -> PhotoRecord:
        now = datetime.now().isoformat(timespec="seconds")
        connection = initialize_database(self.db_path)
        try:
            existing = connection.execute(
                """
                SELECT id, created_at FROM photos
                WHERE project_id = ? AND original_path = ?
                """,
                (self.project_id, str(Path(record.original_path).resolve())),
            ).fetchone()

            values = (
                record.file_hash,
                record.file_size,
                record.mtime_ns,
                str(record.thumbnail_path) if record.thumbnail_path else None,
                _dt(record.capture_date),
                record.date_reliability.value,
                record.metadata_source,
                record.filename_year,
                record.age_from_dob,
                _dt(record.file_created_at),
                _dt(record.file_modified_at),
                1 if record.target_found else 0,
                record.identity_score,
                record.estimated_age,
                record.age_confidence,
                record.face_quality,
                record.overall_confidence,
                record.manual_age,
                record.manual_order,
                record.sort_score,
                record.review_status.value,
                record.selected_face_id,
                record.error_message,
                now,
            )

            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO photos (
                        project_id, original_path, file_hash, file_size, mtime_ns,
                        thumbnail_path, capture_date, date_reliability, metadata_source,
                        filename_year, age_from_dob, file_created_at, file_modified_at,
                        target_found, identity_score, estimated_age, age_confidence,
                        face_quality, overall_confidence, manual_age, manual_order,
                        sort_score, review_status, selected_face_id, error_message,
                        created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        self.project_id,
                        str(Path(record.original_path).resolve()),
                        *values[:-1],
                        now,
                        now,
                    ),
                )
                record.id = int(cursor.lastrowid)
                record.created_at = datetime.fromisoformat(now)
            else:
                connection.execute(
                    """
                    UPDATE photos SET
                        file_hash = ?,
                        file_size = ?,
                        mtime_ns = ?,
                        thumbnail_path = ?,
                        capture_date = ?,
                        date_reliability = ?,
                        metadata_source = ?,
                        filename_year = ?,
                        age_from_dob = ?,
                        file_created_at = ?,
                        file_modified_at = ?,
                        target_found = ?,
                        identity_score = ?,
                        estimated_age = ?,
                        age_confidence = ?,
                        face_quality = ?,
                        overall_confidence = ?,
                        manual_age = ?,
                        manual_order = ?,
                        sort_score = ?,
                        review_status = ?,
                        selected_face_id = ?,
                        error_message = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (*values, existing["id"]),
                )
                record.id = int(existing["id"])
                record.created_at = _parse_optional_datetime(existing["created_at"])

            connection.commit()
            record.updated_at = datetime.fromisoformat(now)
            return record
        finally:
            connection.close()

    def delete_missing_paths(self, keep_paths: set[str]) -> int:
        """Remove DB rows whose original files are no longer in the keep set."""
        connection = initialize_database(self.db_path)
        try:
            rows = connection.execute(
                "SELECT id, original_path FROM photos WHERE project_id = ?",
                (self.project_id,),
            ).fetchall()
            deleted = 0
            for row in rows:
                if row["original_path"] not in keep_paths:
                    connection.execute("DELETE FROM photos WHERE id = ?", (row["id"],))
                    deleted += 1
            connection.commit()
            if deleted:
                logger.info(
                    "Removed %s stale photo rows from project %s",
                    deleted,
                    self.project_id,
                )
            return deleted
        finally:
            connection.close()

    def _row_to_record(self, row) -> PhotoRecord:
        reliability_raw = row["date_reliability"] or DateReliability.NONE.value
        try:
            reliability = DateReliability(reliability_raw)
        except ValueError:
            reliability = DateReliability.NONE

        status_raw = row["review_status"] or ReviewStatus.PENDING.value
        try:
            status = ReviewStatus(status_raw)
        except ValueError:
            status = ReviewStatus.PENDING

        keys = set(row.keys())
        return PhotoRecord(
            id=row["id"],
            project_id=row["project_id"],
            original_path=Path(row["original_path"]),
            file_hash=row["file_hash"],
            file_size=row["file_size"],
            mtime_ns=row["mtime_ns"],
            thumbnail_path=Path(row["thumbnail_path"]) if row["thumbnail_path"] else None,
            capture_date=_parse_optional_datetime(row["capture_date"]),
            date_reliability=reliability,
            metadata_source=row["metadata_source"] if "metadata_source" in keys else None,
            filename_year=row["filename_year"] if "filename_year" in keys else None,
            age_from_dob=row["age_from_dob"] if "age_from_dob" in keys else None,
            file_created_at=_parse_optional_datetime(row["file_created_at"]),
            file_modified_at=_parse_optional_datetime(row["file_modified_at"]),
            target_found=bool(row["target_found"]),
            identity_score=row["identity_score"],
            estimated_age=row["estimated_age"],
            age_confidence=row["age_confidence"],
            face_quality=row["face_quality"],
            overall_confidence=row["overall_confidence"],
            manual_age=row["manual_age"],
            manual_order=row["manual_order"],
            sort_score=row["sort_score"],
            review_status=status,
            selected_face_id=row["selected_face_id"],
            error_message=row["error_message"],
            created_at=_parse_optional_datetime(row["created_at"]),
            updated_at=_parse_optional_datetime(row["updated_at"]),
        )
