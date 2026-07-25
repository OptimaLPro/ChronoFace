"""Apply lossless rotation to a project photo and refresh derived data."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from src.database.face_repository import FaceRepository
from src.database.photo_repository import PhotoRepository
from src.domain.models import PhotoRecord
from src.utils.hashing import sha256_file
from src.utils.image_utils import create_thumbnail, thumbnail_filename_for
from src.utils.lossless_rotate import RotateDirection, rotate_image_lossless
from src.utils.paths import project_cache_dir


def transform_bbox_after_rotate(
    bbox_x: float,
    bbox_y: float,
    bbox_w: float,
    bbox_h: float,
    *,
    image_width: int,
    image_height: int,
    direction: RotateDirection | str,
) -> tuple[float, float, float, float]:
    """
    Map an axis-aligned bbox through a 90° image rotation.

    Coordinates are in the raw pixel space used by OpenCV / face detection
    (stored pixels, before any EXIF display transpose).
    """
    direction = RotateDirection(direction)
    x, y, w, h = float(bbox_x), float(bbox_y), float(bbox_w), float(bbox_h)
    if direction is RotateDirection.RIGHT:
        # 90° clockwise: (x, y) -> (H - y - h, x); size (w,h) -> (h,w)
        return image_height - y - h, x, h, w
    # 90° counter-clockwise: (x, y) -> (y, W - x - w)
    return y, image_width - x - w, h, w


def _raw_image_size(path: Path) -> tuple[int, int]:
    """Return stored pixel (width, height) — matches ``read_image_bgr`` space."""
    try:
        with Image.open(path) as image:
            return int(image.size[0]), int(image.size[1])
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Could not read image size: {path}") from exc


def rotate_project_photo(
    project_id: str,
    photo: PhotoRecord,
    direction: RotateDirection | str,
    *,
    keep_timestamp: bool = True,
) -> PhotoRecord:
    """
    Lossless-rotate the original file and rebuild the thumbnail.

    Analysis scores, review status, embeddings, and face crops stay — same face,
    new orientation. Only file metadata and face bounding boxes are updated.
    """
    direction = RotateDirection(direction)
    path = Path(photo.original_path)
    width, height = _raw_image_size(path)

    faces: list = []
    face_repo: FaceRepository | None = None
    if photo.id is not None:
        face_repo = FaceRepository(project_id)
        faces = face_repo.list_faces_for_photo(photo.id)

    rotate_image_lossless(path, direction, keep_timestamp=keep_timestamp)

    if face_repo is not None:
        for face in faces:
            if face.id is None:
                continue
            nx, ny, nw, nh = transform_bbox_after_rotate(
                face.bbox_x,
                face.bbox_y,
                face.bbox_w,
                face.bbox_h,
                image_width=width,
                image_height=height,
                direction=direction,
            )
            face_repo.update_face_bbox(
                face.id, bbox_x=nx, bbox_y=ny, bbox_w=nw, bbox_h=nh
            )

    file_hash = sha256_file(path)
    stat = path.stat()
    thumbs_dir = project_cache_dir(project_id) / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumbs_dir / thumbnail_filename_for(file_hash)
    create_thumbnail(path, thumb_path)

    photo.file_hash = file_hash
    photo.file_size = stat.st_size
    photo.mtime_ns = stat.st_mtime_ns
    photo.thumbnail_path = thumb_path
    # Keep target_found, scores, ages, review_status, selected_face_id.

    return PhotoRepository(project_id).upsert(photo)
