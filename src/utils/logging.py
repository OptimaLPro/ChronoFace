"""Structured logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.utils.paths import logs_dir


_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure root logging once and return the application logger."""
    global _CONFIGURED

    logger = logging.getLogger("chronoface")
    if _CONFIGURED:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    log_file: Path = logs_dir() / "app.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    _CONFIGURED = True
    logger.info("Logging initialized (file=%s)", log_file)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the application namespace."""
    if name:
        return logging.getLogger(f"chronoface.{name}")
    return logging.getLogger("chronoface")
