"""Smoke tests for the animated startup splash."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from src.ui.splash_screen import StartupSplash, _ChronoMark, _ShimmerBar


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_splash_shows_brand_and_status(qapp: QApplication) -> None:
    splash = StartupSplash()
    labels = [w.text() for w in splash.findChildren(QLabel)]
    assert "ChronoFace" in labels
    assert any("age" in text.lower() for text in labels)
    splash.set_status("Loading interface…")
    assert splash._status.text() == "Loading interface…"
    splash.close()


def test_loader_widgets_paint(qapp: QApplication) -> None:
    mark = _ChronoMark()
    bar = _ShimmerBar()
    mark.resize(168, 168)
    bar.resize(240, 6)
    assert not mark.grab().isNull()
    assert not bar.grab().isNull()
    mark.stop()
    bar.stop()


def test_finish_with_shows_window(qapp: QApplication) -> None:
    splash = StartupSplash()
    splash._shown_at = 0.0  # skip minimum-visible delay
    window = QWidget()
    window.setWindowTitle("ChronoFace Test")
    splash.finish_with(window)
    assert window.isVisible()
    splash._on_fade_done()
    assert not splash.isVisible()
