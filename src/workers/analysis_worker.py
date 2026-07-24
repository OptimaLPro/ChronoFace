"""Background analysis worker (metadata + face recognition)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QObject, Signal

from src.domain.models import ReferencePhoto, ScanSummary
from src.utils.logging import get_logger
from src.workers.face_pipeline import FaceAnalysisPipeline, FacePipelineConfig
from src.workers.metadata_pipeline import MetadataPipeline, MetadataPipelineConfig

logger = get_logger("workers.analysis_worker")


class AnalysisWorker(QObject):
    """
    Runs photo processing off the UI thread.

    Phase 2: metadata discovery, hashing, EXIF, thumbnails.
    Phase 3: face detection, embeddings, identity matching.
    """

    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(object)  # ScanSummary
    error = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        *,
        project_id: str,
        input_folder: Path,
        date_of_birth: Optional[date] = None,
        reference_photos: Sequence[ReferencePhoto] | None = None,
        include_subfolders: bool = True,
        force_reprocess: bool = False,
        force_face_reprocess: bool = False,
        run_face_analysis: bool = True,
    ) -> None:
        super().__init__()
        self._project_id = project_id
        self._input_folder = Path(input_folder)
        self._date_of_birth = date_of_birth
        self._reference_photos = list(reference_photos or [])
        self._include_subfolders = include_subfolders
        self._force_reprocess = force_reprocess
        self._force_face_reprocess = force_face_reprocess
        self._run_face_analysis = run_face_analysis
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            metadata = MetadataPipeline(
                MetadataPipelineConfig(
                    project_id=self._project_id,
                    input_folder=self._input_folder,
                    date_of_birth=self._date_of_birth,
                    recursive=self._include_subfolders,
                    force_reprocess=self._force_reprocess,
                )
            )
            summary: ScanSummary = metadata.run(
                on_progress=self._emit_progress,
                should_cancel=lambda: self._cancel_requested,
            )
            if summary.cancelled or self._cancel_requested:
                self.cancelled.emit()
                return

            if self._run_face_analysis:
                if not self._reference_photos:
                    raise RuntimeError(
                        "Reference photos are required for face matching."
                    )
                faces = FaceAnalysisPipeline(
                    FacePipelineConfig(
                        project_id=self._project_id,
                        reference_photos=self._reference_photos,
                        date_of_birth=self._date_of_birth,
                        force_reprocess=(
                            self._force_reprocess or self._force_face_reprocess
                        ),
                    )
                )
                summary = faces.run(
                    on_progress=self._emit_progress,
                    should_cancel=lambda: self._cancel_requested,
                    base_summary=summary,
                )
                if summary.cancelled or self._cancel_requested:
                    self.cancelled.emit()
                    return

            self.finished.emit(summary)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Analysis worker failed")
            message = str(exc).strip() or repr(exc) or type(exc).__name__
            if isinstance(exc, AssertionError) and not str(exc).strip():
                message = (
                    "InsightFace failed to load the selected model pack "
                    "(missing detection model files).\n\n"
                    "This often happens with antelopev2 when the zip unpacks into a "
                    "nested folder. Try Analyze again after restarting the app, "
                    "or switch Settings → Models to buffalo_l (recommended)."
                )
            self.error.emit(message)

    def _emit_progress(self, current: int, total: int, message: str) -> None:
        self.progress.emit(current, total, message)
