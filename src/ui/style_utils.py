"""Shared Qt style helpers."""

from __future__ import annotations

# Table/list stylesheets force Qt's stylesheet engine onto child scrollbars.
# Without explicit QScrollBar rules, Fusion often paints solid black handles.
# These rules restore a normal light system-like scrollbar everywhere.
DEFAULT_SCROLLBAR_STYLE = """
QScrollBar:vertical {
    background: #f0f0f0;
    width: 14px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #c1c1c1;
    min-height: 24px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background: #a8a8a8;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
    border: none;
    background: none;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background: #f0f0f0;
    height: 14px;
    margin: 0px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #c1c1c1;
    min-width: 24px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background: #a8a8a8;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
    border: none;
    background: none;
}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: none;
}
"""
