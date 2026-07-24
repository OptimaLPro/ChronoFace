"""Summary dialog shown after a numbered photo export finishes."""

from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.export.file_exporter import ExportResult
from src.ui.icons import icon_pixmap
from src.ui.message_dialog import OverlayDialog
from src.ui import theme as T
from src.utils.paths import open_in_file_manager, reveal_in_file_manager


class ExportCompleteDialog(OverlayDialog):
    """Export summary with clickable paths that open in the file manager."""

    def __init__(
        self,
        result: ExportResult,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, min_card_width=520, max_card_width=640)
        self.setWindowTitle("Export Complete")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._output_dir = self._resolve_output_dir(result)
        self._csv_path = result.csv_path

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        icon.setFixedSize(40, 40)
        icon.setPixmap(icon_pixmap("check-circle", size=36, color=T.SUCCESS))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel("Export Complete")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {T.TEXT}; border: none;"
        )
        summary = QLabel(
            f"Copied {result.exported_main} numbered photos."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {T.SUCCESS}; border: none;"
        )
        titles.addWidget(title)
        titles.addWidget(summary)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(titles, 1)

        self._card_layout.addLayout(header)

        if self._output_dir is not None:
            self._card_layout.addLayout(
                self._path_block(
                    "Export folder",
                    self._output_dir,
                    hint="Click to open in File Explorer",
                    open_folder=True,
                )
            )

        stats = QLabel(
            f"Unresolved folder copies: {result.exported_unresolved}\n"
            f"Excluded folder copies: {result.exported_excluded}"
        )
        stats.setWordWrap(True)
        stats.setStyleSheet(
            f"font-size: 13px; color: {T.TEXT}; border: none; line-height: 1.45;"
        )
        self._card_layout.addWidget(stats)

        if self._csv_path is not None:
            self._card_layout.addLayout(
                self._path_block(
                    "CSV report",
                    self._csv_path,
                    hint="Click to show in File Explorer",
                    open_folder=False,
                )
            )

        if result.errors:
            errors = QLabel(
                "Some files failed:\n" + "\n".join(result.errors[:8])
            )
            errors.setWordWrap(True)
            errors.setStyleSheet(
                f"font-size: 12px; color: {T.ERROR}; background: {T.BACKGROUND};"
                f" border: 1px solid {T.BORDER}; border-radius: 10px;"
                " padding: 10px 12px;"
            )
            self._card_layout.addWidget(errors)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)

        if self._output_dir is not None:
            open_btn = QPushButton("Open folder")
            open_btn.setObjectName("ghostButton")
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.clicked.connect(self._open_output_dir)
            buttons.addWidget(open_btn)

        ok = QPushButton("OK")
        ok.setObjectName("primaryButton")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)

        self._card_layout.addLayout(buttons)
        self._layout_card()

    def _path_block(
        self,
        label: str,
        path: Path,
        *,
        hint: str,
        open_folder: bool,
    ) -> QVBoxLayout:
        block = QVBoxLayout()
        block.setSpacing(4)

        heading = QLabel(label)
        heading.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {T.TEXT_MUTED};"
            " border: none; letter-spacing: 0.04em;"
        )

        location = str(path)
        href = QUrl.fromLocalFile(location).toString()
        link = QLabel(
            f'<a href="{href}" style="color:{T.PRIMARY}; text-decoration:underline;">'
            f"{escape(location)}</a>"
        )
        link.setObjectName("pathLinkLabel")
        link.setWordWrap(True)
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setOpenExternalLinks(False)
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.setToolTip(hint)
        link.setStyleSheet(
            f"font-size: 13px; color: {T.PRIMARY}; border: none;"
            f" background: {T.BACKGROUND}; border-radius: 8px;"
            " padding: 10px 12px;"
        )
        if open_folder:
            link.linkActivated.connect(lambda _href: self._open_output_dir())
        else:
            link.linkActivated.connect(lambda _href: self._reveal_csv())

        block.addWidget(heading)
        block.addWidget(link)
        return block

    def _open_output_dir(self) -> None:
        if self._output_dir is None:
            return
        try:
            open_in_file_manager(self._output_dir)
        except FileNotFoundError:
            pass

    def _reveal_csv(self) -> None:
        if self._csv_path is None:
            return
        try:
            reveal_in_file_manager(self._csv_path)
        except FileNotFoundError:
            pass

    @staticmethod
    def _resolve_output_dir(result: ExportResult) -> Path | None:
        if result.output_dir is not None:
            return Path(result.output_dir)
        if result.csv_path is not None:
            return Path(result.csv_path).parent
        if result.items:
            dest = Path(result.items[0].destination)
            if dest.parent.name in {"_unresolved", "_excluded"}:
                return dest.parent.parent
            return dest.parent
        return None
