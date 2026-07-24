"""Tests for InsightFace pack layout repair (nested zip folders)."""

from __future__ import annotations

from pathlib import Path

from src.vision import model_manager as mm


def test_flatten_nested_antelope_pack(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "insightface"
    pack = root / "models" / "antelopev2"
    nested = pack / "antelopev2"
    nested.mkdir(parents=True)
    # Fake large onnx-ish files
    (nested / "scrfd_10g_bnkps.onnx").write_bytes(b"x" * 1000)
    (nested / "glintr100.onnx").write_bytes(b"y" * 1000)
    (nested / "genderage.onnx").write_bytes(b"z" * 100)

    monkeypatch.setattr(mm, "insightface_root", lambda: root)
    monkeypatch.setattr(mm, "INSIGHTFACE_PACK_MIN_BYTES", 500)

    assert not mm.insightface_pack_ready("antelopev2")
    moved = mm.flatten_insightface_pack("antelopev2")
    assert moved is True
    assert mm.insightface_pack_ready("antelopev2")
    assert (pack / "scrfd_10g_bnkps.onnx").is_file()
    assert not nested.exists()


def test_ready_pack_is_not_moved(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "insightface"
    pack = root / "models" / "buffalo_l"
    pack.mkdir(parents=True)
    (pack / "det_10g.onnx").write_bytes(b"x" * 1000)
    (pack / "w600k_r50.onnx").write_bytes(b"y" * 1000)

    monkeypatch.setattr(mm, "insightface_root", lambda: root)
    monkeypatch.setattr(mm, "INSIGHTFACE_PACK_MIN_BYTES", 500)

    assert mm.insightface_pack_ready("buffalo_l")
    assert mm.flatten_insightface_pack("buffalo_l") is False
