"""Download and locate local ONNX vision models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve

from src.utils.logging import get_logger
from src.utils.paths import project_root

logger = get_logger("vision.model_manager")

# OpenCV Zoo models — Apache/BSD-friendly ecosystem; verify license before redistribution.
YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
SFACE_FILENAME = "face_recognition_sface_2021dec.onnx"
AGE_FILENAME = "age_efficientnet_b2.onnx"

YUNET_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
    "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
SFACE_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
    "models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
)
# FaceONNX-derived EfficientNet age model (MIT FaceONNX ecosystem).
AGE_URL = (
    "https://huggingface.co/talmago/face.onnx/resolve/main/onnx/age_efficientnet_b2.onnx"
)

YUNET_MIN_BYTES = 100_000
SFACE_MIN_BYTES = 1_000_000
AGE_MIN_BYTES = 1_000_000

# Minimum on-disk size to treat an InsightFace pack as present.
INSIGHTFACE_PACK_MIN_BYTES = 5_000_000


@dataclass(frozen=True)
class FaceModelPaths:
    detector: Path
    recognizer: Path


@dataclass(frozen=True)
class AgeModelPath:
    estimator: Path


@dataclass(frozen=True)
class ModelInstallStatus:
    preset_id: str
    title: str
    installed: bool
    detail: str
    path: Path | None = None


def models_dir() -> Path:
    """Return the project models directory."""
    path = project_root() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def insightface_root() -> Path:
    """Root folder passed to InsightFace FaceAnalysis (contains models/<pack>)."""
    path = models_dir() / "insightface"
    path.mkdir(parents=True, exist_ok=True)
    return path


def insightface_pack_dir(pack_name: str) -> Path:
    return insightface_root() / "models" / pack_name


def _download(url: str, destination: Path, min_bytes: int) -> Path:
    if destination.exists() and destination.stat().st_size >= min_bytes:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".partial")
    logger.info("Downloading model %s", destination.name)
    try:
        urlretrieve(url, temp_path)
        size = temp_path.stat().st_size
        if size < min_bytes:
            temp_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"Downloaded model looks invalid ({destination.name}, {size} bytes). "
                "Git LFS pointer files are not usable — check the download URL."
            )
        temp_path.replace(destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    logger.info("Model ready: %s (%s bytes)", destination, destination.stat().st_size)
    return destination


def ensure_face_models(*, download: bool = True) -> FaceModelPaths:
    """Ensure YuNet + SFace ONNX files exist under ``models/``."""
    detector = models_dir() / YUNET_FILENAME
    recognizer = models_dir() / SFACE_FILENAME

    if download:
        _download(YUNET_URL, detector, YUNET_MIN_BYTES)
        _download(SFACE_URL, recognizer, SFACE_MIN_BYTES)
    else:
        if not detector.exists() or detector.stat().st_size < YUNET_MIN_BYTES:
            raise FileNotFoundError(f"Missing face detector model: {detector}")
        if not recognizer.exists() or recognizer.stat().st_size < SFACE_MIN_BYTES:
            raise FileNotFoundError(f"Missing face recognizer model: {recognizer}")

    return FaceModelPaths(detector=detector, recognizer=recognizer)


def ensure_age_model(*, download: bool = True) -> AgeModelPath:
    """Ensure the facial age-estimation ONNX model exists under ``models/``."""
    estimator = models_dir() / AGE_FILENAME
    if download:
        _download(AGE_URL, estimator, AGE_MIN_BYTES)
    elif not estimator.exists() or estimator.stat().st_size < AGE_MIN_BYTES:
        raise FileNotFoundError(f"Missing age estimation model: {estimator}")
    return AgeModelPath(estimator=estimator)


def _dir_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def _onnx_files(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(path.glob("*.onnx"))


def _looks_like_detection_model(name: str) -> bool:
    lower = name.lower()
    return lower.startswith("det_") or "scrfd" in lower or "retina" in lower


def insightface_pack_ready(pack_name: str) -> bool:
    """
    True when ONNX files sit directly under models/<pack>/ (not nested).

    InsightFace FaceAnalysis expects ``…/models/antelopev2/*.onnx``.
    Some zips unpack as ``…/models/antelopev2/antelopev2/*.onnx`` which then
    fails with ``AssertionError: 'detection' in self.models``.
    """
    pack_dir = insightface_pack_dir(pack_name)
    files = _onnx_files(pack_dir)
    if not files:
        return False
    if _dir_size(pack_dir) < INSIGHTFACE_PACK_MIN_BYTES:
        return False
    return any(_looks_like_detection_model(path.name) for path in files)


def flatten_insightface_pack(pack_name: str) -> bool:
    """
    Move nested ``models/<pack>/<pack>/*.onnx`` up one level if needed.

    Returns True if files were moved.
    """
    pack_dir = insightface_pack_dir(pack_name)
    if insightface_pack_ready(pack_name):
        return False

    nested = pack_dir / pack_name
    candidates = [nested] if nested.is_dir() else []
    # Also handle a single unexpected child directory that holds the onnx files.
    if not candidates and pack_dir.is_dir():
        child_dirs = [child for child in pack_dir.iterdir() if child.is_dir()]
        if len(child_dirs) == 1 and _onnx_files(child_dirs[0]):
            candidates = child_dirs

    moved = False
    for source in candidates:
        for onnx in _onnx_files(source):
            dest = pack_dir / onnx.name
            if dest.exists():
                continue
            onnx.replace(dest)
            moved = True
            logger.info("Flattened InsightFace model file: %s → %s", onnx, dest)
        # Remove empty nested dirs best-effort.
        try:
            for leftover in sorted(source.rglob("*"), reverse=True):
                if leftover.is_file():
                    continue
                leftover.rmdir()
            if source.exists():
                source.rmdir()
        except OSError:
            pass

    return moved


def insightface_pack_installed(pack_name: str) -> bool:
    flatten_insightface_pack(pack_name)
    return insightface_pack_ready(pack_name)


def ensure_insightface_pack(pack_name: str, *, download: bool = True) -> Path:
    """
    Ensure an InsightFace model pack exists under ``models/insightface/models/``.

    When missing and ``download`` is True, trigger InsightFace's own downloader
    by constructing a temporary FaceAnalysis instance, then flatten nested zips.
    """
    pack_dir = insightface_pack_dir(pack_name)
    flatten_insightface_pack(pack_name)
    if insightface_pack_ready(pack_name):
        return pack_dir

    if not download:
        raise FileNotFoundError(
            f"InsightFace pack '{pack_name}' is not installed at {pack_dir}"
        )

    from src.vision.insightface_backend import insightface_available

    if not insightface_available():
        raise RuntimeError(
            "Cannot download InsightFace models because the 'insightface' "
            "package is not installed.\n"
            "Run: pip install insightface onnx"
        )

    logger.info("Downloading InsightFace pack '%s' (first run may take a while)…", pack_name)
    from insightface.app import FaceAnalysis

    try:
        # FaceAnalysis downloads into root/models/<name> when missing.
        # Nested zip layouts are fixed by flatten_insightface_pack below.
        app = FaceAnalysis(
            name=pack_name,
            root=str(insightface_root()),
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=0, det_size=(640, 640))
        del app
    except AssertionError as exc:
        # Common when zip unpacked into models/antelopev2/antelopev2/*.onnx
        flatten_insightface_pack(pack_name)
        if insightface_pack_ready(pack_name):
            logger.info(
                "Repaired nested InsightFace pack layout for '%s'", pack_name
            )
            return pack_dir
        raise RuntimeError(
            f"InsightFace pack '{pack_name}' downloaded but could not be loaded.\n"
            f"Expected ONNX files (including a detection model) directly under:\n"
            f"  {pack_dir}\n\n"
            "If a nested folder exists, move the .onnx files up one level, "
            "or switch Settings → Models to buffalo_l.\n\n"
            f"Details: {exc or repr(exc)}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        flatten_insightface_pack(pack_name)
        if insightface_pack_ready(pack_name):
            return pack_dir
        raise RuntimeError(
            f"Failed to prepare InsightFace pack '{pack_name}'.\n"
            f"Folder: {pack_dir}\n\n"
            "Tip: buffalo_l is the recommended pack and downloads more reliably. "
            "antelopev2 often ships with a nested zip layout that breaks loading.\n\n"
            f"Details: {exc or type(exc).__name__}"
        ) from exc

    flatten_insightface_pack(pack_name)
    if not insightface_pack_ready(pack_name):
        raise RuntimeError(
            f"InsightFace pack '{pack_name}' did not install correctly.\n"
            f"Expected detection + recognition ONNX files under:\n  {pack_dir}\n"
            "Switch to buffalo_l in Settings, or place the .onnx files there manually."
        )
    logger.info("InsightFace pack ready: %s", pack_dir)
    return pack_dir


def opencv_models_installed() -> bool:
    detector = models_dir() / YUNET_FILENAME
    recognizer = models_dir() / SFACE_FILENAME
    age = models_dir() / AGE_FILENAME
    return (
        detector.exists()
        and detector.stat().st_size >= YUNET_MIN_BYTES
        and recognizer.exists()
        and recognizer.stat().st_size >= SFACE_MIN_BYTES
        and age.exists()
        and age.stat().st_size >= AGE_MIN_BYTES
    )


def describe_install_status(*, probe_mivolo: bool = False) -> list[ModelInstallStatus]:
    """
    Status rows for the Settings UI.

    By default uses a cheap package presence check for MiVOLO (no torch import).
    Pass probe_mivolo=True from a background thread to also resolve CUDA/CPU.
    """
    from src.vision.insightface_backend import insightface_available
    from src.vision.mivolo_age import (
        mivolo_cache_dir,
        mivolo_deps_error,
        mivolo_deps_present,
        mivolo_installed,
        resolve_mivolo_device,
        warm_mivolo_imports,
    )
    from src.vision.model_catalog import list_presets

    rows: list[ModelInstallStatus] = []
    for preset in list_presets():
        if preset.pack_name is None:
            installed = opencv_models_installed()
            detail = "Installed" if installed else "Not downloaded yet"
            rows.append(
                ModelInstallStatus(
                    preset_id=preset.id.value,
                    title=preset.title,
                    installed=installed,
                    detail=detail,
                    path=models_dir(),
                )
            )
            continue

        if not insightface_available():
            rows.append(
                ModelInstallStatus(
                    preset_id=preset.id.value,
                    title=preset.title,
                    installed=False,
                    detail="Requires: pip install insightface onnx",
                    path=insightface_pack_dir(preset.pack_name),
                )
            )
            continue

        installed = insightface_pack_installed(preset.pack_name)
        size_mb = _dir_size(insightface_pack_dir(preset.pack_name)) / (1024 * 1024)
        detail = (
            f"Installed ({size_mb:.0f} MB)"
            if installed
            else "Not downloaded yet (will auto-download on first use)"
        )
        rows.append(
            ModelInstallStatus(
                preset_id=preset.id.value,
                title=preset.title,
                installed=installed,
                detail=detail,
                path=insightface_pack_dir(preset.pack_name),
            )
        )

    # Age backend (MiVOLO) — independent of identity pack.
    # Avoid importing torch on the UI thread; optionally warm imports in a worker.
    deps_ok = mivolo_deps_present()
    if probe_mivolo and deps_ok:
        deps_ok = warm_mivolo_imports()

    if not deps_ok:
        rows.append(
            ModelInstallStatus(
                preset_id="age_mivolo_v2",
                title="Age: MiVOLO v2",
                installed=False,
                detail=(
                    f"Requires torch + transformers "
                    f"({mivolo_deps_error() or 'not installed'})"
                ),
                path=mivolo_cache_dir(),
            )
        )
    else:
        installed = mivolo_installed()
        device = resolve_mivolo_device(probe=probe_mivolo)
        size_mb = _dir_size(mivolo_cache_dir()) / (1024 * 1024)
        if device == "pending":
            device_note = "device check pending"
        else:
            device_note = f"device: {device}"
        if installed:
            detail = f"Installed ({size_mb:.0f} MB) — {device_note}"
        else:
            detail = (
                f"Deps OK ({device_note}); weights download on first use "
                "or via Download Selected"
            )
        rows.append(
            ModelInstallStatus(
                preset_id="age_mivolo_v2",
                title="Age: MiVOLO v2",
                installed=installed,
                detail=detail,
                path=mivolo_cache_dir(),
            )
        )
    return rows


def ensure_models_for_preset(preset_id: str, *, download: bool = True) -> None:
    from src.vision.model_catalog import BackendFamily, get_preset

    if preset_id == "age_mivolo_v2":
        from src.vision.mivolo_age import ensure_mivolo_model

        ensure_mivolo_model(download=download)
        return

    preset = get_preset(preset_id)
    if preset.backend == BackendFamily.OPENCV:
        ensure_face_models(download=download)
        ensure_age_model(download=download)
    else:
        assert preset.pack_name is not None
        ensure_insightface_pack(preset.pack_name, download=download)
