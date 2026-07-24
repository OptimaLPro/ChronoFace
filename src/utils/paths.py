"""Application path helpers (Windows-friendly, macOS-ready)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "ChronoFace"


def project_root() -> Path:
    """Return the repository root (folder containing app.py), or exe dir when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    """
    Return the per-user application data directory.

    Windows: %LOCALAPPDATA%\\ChronoFace
    macOS:   ~/Library/Application Support/ChronoFace
    Linux:   ~/.local/share/ChronoFace
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def projects_dir() -> Path:
    """Directory that stores per-project SQLite databases and caches."""
    path = app_data_dir() / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_dir(project_id: str) -> Path:
    """Return (and create) the on-disk folder for a single project."""
    path = projects_dir() / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_db_path(project_id: str) -> Path:
    """SQLite database path for a project."""
    return project_dir(project_id) / "project.db"


def project_cache_dir(project_id: str) -> Path:
    """Cache directory for thumbnails, face crops, and embeddings."""
    path = project_dir(project_id) / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    """Directory for application log files."""
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def recent_projects_index_path() -> Path:
    """SQLite index of recently opened projects."""
    return app_data_dir() / "app_index.db"
