"""Background export worker."""

from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from PySide6.QtCore import QObject, Signal

from src.database.photo_repository import PhotoRepository
from src.domain.models import PhotoRecord
from src.export.csv_exporter import export_csv_report
from src.export.file_exporter import ExportOptions, ExportResult, export_numbered_copies
from src.sorting.ranking import rank_photo_records
from src.utils.logging import get_logger

logger = get_logger("workers.export_worker")


class ExportWorker(QObject):
    """Copy numbered photos on a background thread."""

    progress = Signal(int, int, str)
    finished = Signal(object)  # ExportResult
    error = Signal(str)

    def __init__(
        self,
        *,
        project_id: str,
        options: ExportOptions,
        date_of_birth: Optional[date] = None,
        photos: Sequence[PhotoRecord] | None = None,
    ) -> None:
        super().__init__()
        self._project_id = project_id
        self._options = options
        self._date_of_birth = date_of_birth
        self._photos = list(photos) if photos is not None else None

    def run(self) -> None:
        try:
            if self._photos is None:
                photos = PhotoRepository(self._project_id).list_photos()
            else:
                photos = list(self._photos)

            ranked = rank_photo_records(
                photos,
                date_of_birth=self._date_of_birth,
            )
            result: ExportResult = export_numbered_copies(
                ranked,
                self._options,
                on_progress=self._emit_progress,
            )
            if self._options.write_csv:
                csv_path = self._options.output_dir / "export_report.csv"
                result.csv_path = export_csv_report(result.items, csv_path)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Export failed")
            self.error.emit(str(exc))

    def _emit_progress(self, current: int, total: int, message: str) -> None:
        self.progress.emit(current, total, message)
