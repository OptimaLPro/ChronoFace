"""SQLite schema definitions and migration runner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.utils.logging import get_logger

logger = get_logger("database.migrations")

SCHEMA_VERSION = 3

# Base schema (v1+) with placeholder tables for later phases.
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    input_folder TEXT NOT NULL,
    output_folder TEXT NOT NULL,
    date_of_birth TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    life_stage TEXT NOT NULL DEFAULT 'unknown',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);

-- Phase 2+: discovered / analyzed photos
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    original_path TEXT NOT NULL,
    file_hash TEXT,
    file_size INTEGER,
    mtime_ns INTEGER,
    thumbnail_path TEXT,
    capture_date TEXT,
    date_reliability TEXT,
    metadata_source TEXT,
    filename_year INTEGER,
    age_from_dob REAL,
    file_created_at TEXT,
    file_modified_at TEXT,
    target_found INTEGER NOT NULL DEFAULT 0,
    identity_score REAL,
    estimated_age REAL,
    age_confidence REAL,
    face_quality REAL,
    overall_confidence REAL,
    manual_age REAL,
    manual_order INTEGER,
    sort_score REAL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    selected_face_id INTEGER,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, original_path),
    FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);

-- Phase 3+: detected faces per photo
CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL,
    bbox_x REAL NOT NULL,
    bbox_y REAL NOT NULL,
    bbox_w REAL NOT NULL,
    bbox_h REAL NOT NULL,
    embedding_path TEXT,
    face_crop_path TEXT,
    quality_score REAL,
    identity_score REAL,
    estimated_age REAL,
    is_selected_target INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reference_photos_project
    ON reference_photos(project_id);

CREATE INDEX IF NOT EXISTS idx_photos_project
    ON photos(project_id);

CREATE INDEX IF NOT EXISTS idx_photos_sort
    ON photos(project_id, sort_score, manual_order);

CREATE INDEX IF NOT EXISTS idx_faces_photo
    ON faces(photo_id);

CREATE TABLE IF NOT EXISTS reference_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    reference_photo_id INTEGER,
    source_path TEXT NOT NULL,
    life_stage TEXT NOT NULL DEFAULT 'unknown',
    embedding_path TEXT NOT NULL,
    detection_score REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reference_embeddings_project
    ON reference_embeddings(project_id);
"""

# Additive migrations for databases created at an earlier schema version.
MIGRATIONS: dict[int, str] = {
    2: """
    ALTER TABLE photos ADD COLUMN metadata_source TEXT;
    ALTER TABLE photos ADD COLUMN filename_year INTEGER;
    ALTER TABLE photos ADD COLUMN age_from_dob REAL;
    """,
    3: """
    CREATE TABLE IF NOT EXISTS reference_embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        reference_photo_id INTEGER,
        source_path TEXT NOT NULL,
        life_stage TEXT NOT NULL DEFAULT 'unknown',
        embedding_path TEXT NOT NULL,
        detection_score REAL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_reference_embeddings_project
        ON reference_embeddings(project_id);
    """,
}

def connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_schema_version(connection: sqlite3.Connection) -> int:
    """Read the stored schema version, or 0 if unset."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return 0
    return int(row["value"])


def set_schema_version(connection: sqlite3.Connection, version: int) -> None:
    """Persist the schema version."""
    connection.execute(
        """
        INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (str(version),),
    )


def initialize_database(db_path: Path) -> sqlite3.Connection:
    """Create or upgrade a project database and return an open connection."""
    connection = connect(db_path)
    current = get_schema_version(connection)

    if current == 0:
        logger.info("Creating database schema v%s for %s", SCHEMA_VERSION, db_path)
        connection.executescript(SCHEMA_SQL)
        set_schema_version(connection, SCHEMA_VERSION)
        connection.commit()
        return connection

    for version in range(current + 1, SCHEMA_VERSION + 1):
        sql = MIGRATIONS.get(version)
        if not sql:
            set_schema_version(connection, version)
            connection.commit()
            continue
        logger.info(
            "Migrating database %s from v%s to v%s",
            db_path,
            version - 1,
            version,
        )
        for statement in sql.strip().split(";"):
            statement = statement.strip()
            if not statement:
                continue
            try:
                connection.execute(statement)
            except sqlite3.OperationalError as exc:
                # Column may already exist if SCHEMA_SQL was re-applied.
                if "duplicate column" not in str(exc).lower():
                    raise
        set_schema_version(connection, version)
        connection.commit()

    return connection


APP_INDEX_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS recent_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    db_path TEXT NOT NULL,
    input_folder TEXT NOT NULL,
    output_folder TEXT NOT NULL,
    last_opened_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recent_projects_opened
    ON recent_projects(last_opened_at DESC);
"""


def initialize_app_index(db_path: Path) -> sqlite3.Connection:
    """Create the application-level recent-projects index."""
    connection = connect(db_path)
    connection.executescript(APP_INDEX_SQL)
    connection.commit()
    return connection
