"""Smoke tests for the no-project welcome screen."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.welcome_view import WelcomeView


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_welcome_view_empty_state(qapp: QApplication) -> None:
    view = WelcomeView()
    view.set_recent_projects([])
    assert not view._empty_label.isHidden()
    assert view._recent_list.isHidden()
    assert view._recent_list.count() == 0


def test_welcome_view_lists_recent_and_emits_open(qapp: QApplication) -> None:
    view = WelcomeView()
    opened: list[str] = []
    view.open_project_requested.connect(opened.append)

    view.set_recent_projects(
        [
            {
                "id": "proj-1",
                "name": "Family Album",
                "input_folder": "/photos/family",
                "last_opened_at": "2026-07-20T10:00:00",
            }
        ]
    )
    assert view._empty_label.isHidden()
    assert not view._recent_list.isHidden()
    assert view._recent_list.count() == 1

    item = view._recent_list.item(0)
    assert item is not None
    assert item.data(Qt.ItemDataRole.UserRole) == "proj-1"
    view._on_item_activated(item)
    assert opened == ["proj-1"]


def test_welcome_create_button_emits(qapp: QApplication) -> None:
    view = WelcomeView()
    clicks = SimpleNamespace(count=0)
    view.create_project_requested.connect(lambda: setattr(clicks, "count", clicks.count + 1))
    view._create_button.click()
    assert clicks.count == 1
