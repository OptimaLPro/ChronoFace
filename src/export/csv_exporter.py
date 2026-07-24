"""CSV report export for Premiere / review workflows."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from src.export.file_exporter import ExportItem, effective_age_for_name


CSV_COLUMNS = [
    "output_order",
    "bucket",
    "original_path",
    "output_path",
    "target_found",
    "identity_score",
    "estimated_age",
    "manual_age",
    "age_from_dob",
    "effective_age",
    "capture_date",
    "date_reliability",
    "confidence",
    "review_status",
]


def export_csv_report(items: Iterable[ExportItem], output_path: Path) -> Path:
    """Write an export summary CSV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        order_by_bucket: dict[str, int] = {}
        for item in items:
            bucket = item.bucket
            order_by_bucket[bucket] = order_by_bucket.get(bucket, 0) + 1
            photo = item.photo
            writer.writerow(
                {
                    "output_order": order_by_bucket[bucket],
                    "bucket": bucket,
                    "original_path": str(photo.original_path),
                    "output_path": str(item.destination),
                    "target_found": int(bool(photo.target_found)),
                    "identity_score": (
                        f"{photo.identity_score:.4f}"
                        if photo.identity_score is not None
                        else ""
                    ),
                    "estimated_age": (
                        f"{photo.estimated_age:.2f}"
                        if photo.estimated_age is not None
                        else ""
                    ),
                    "manual_age": (
                        f"{photo.manual_age:.2f}"
                        if photo.manual_age is not None
                        else ""
                    ),
                    "age_from_dob": (
                        f"{photo.age_from_dob:.2f}"
                        if photo.age_from_dob is not None
                        else ""
                    ),
                    "effective_age": (
                        f"{effective_age_for_name(photo):.2f}"
                        if effective_age_for_name(photo) is not None
                        else ""
                    ),
                    "capture_date": (
                        photo.capture_date.isoformat(timespec="seconds")
                        if photo.capture_date
                        else ""
                    ),
                    "date_reliability": photo.date_reliability.value,
                    "confidence": (
                        f"{photo.overall_confidence:.4f}"
                        if photo.overall_confidence is not None
                        else ""
                    ),
                    "review_status": photo.review_status.value,
                }
            )
    return output_path
