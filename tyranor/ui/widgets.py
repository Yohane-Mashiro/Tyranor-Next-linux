from __future__ import annotations

import math
import re
import time
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..i18n import Translator
from ..models import Game


def format_bytes(value: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.0f} {units[index]}" if index == 0 else f"{value:.1f} {units[index]}"


def format_relative_time(timestamp_ms: int, tr: Translator) -> str:
    if timestamp_ms <= 0:
        return tr.text("games.never")
    seconds = max(0, int(time.time() - timestamp_ms / 1000))
    if seconds < 60:
        return "刚刚" if tr.language == "zh_CN" else "just now"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前" if tr.language == "zh_CN" else f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前" if tr.language == "zh_CN" else f"{seconds // 3600} h ago"
    return time.strftime("%Y-%m-%d", time.localtime(timestamp_ms / 1000))


def title_sort_key(value: str, ignore_tags: bool = False) -> str:
    title = value.strip()
    if ignore_tags:
        title = re.sub(r"^(?:\s*[\[【［][^\]】］]{1,30}[\]】］])+\s*", "", title)
    return title.casefold()


def display_title(value: str, hide_tags: bool = False) -> str:
    if not hide_tags:
        return value
    stripped = re.sub(r"^(?:\s*[\[【［][^\]】］]{1,30}[\]】］])+\s*", "", value)
    return stripped or value


class CoverArt(QWidget):
    def __init__(self, game: Game | None = None, parent=None):
        super().__init__(parent)
        self.game = game
        self.setMinimumSize(120, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pixmap = QPixmap()
        self._load()

    def set_game(self, game: Game) -> None:
        self.game = game
        self._load()
        self.update()

    def _load(self) -> None:
        self._pixmap = QPixmap()
        if self.game and self.game.display_cover:
            self._pixmap.load(self.game.display_cover)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.setClipPath(path)
        if not self._pixmap.isNull():
            source = self._pixmap
            scaled = source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (scaled.width() - self.width()) // 2
            y = (scaled.height() - self.height()) // 2
            painter.drawPixmap(0, 0, scaled, x, y, self.width(), self.height())
            shade = QLinearGradient(0, self.height() * 0.55, 0, self.height())
            shade.setColorAt(0, QColor(0, 0, 0, 0))
            shade.setColorAt(1, QColor(5, 10, 22, 160))
            painter.fillRect(self.rect(), shade)
        else:
            base = QColor(self.game.engine.color if self.game else "#5B8DEF")
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0, base.lighter(125))
            gradient.setColorAt(1, base.darker(185))
            painter.fillRect(self.rect(), gradient)
            painter.setPen(QColor(255, 255, 255, 230))
            font = QFont("Noto Sans CJK SC", max(20, min(42, self.width() // 4)))
            font.setBold(True)
            painter.setFont(font)
            glyph = self.game.engine.abbr if self.game else "T"
            painter.drawText(self.rect().adjusted(12, 0, -12, -28), Qt.AlignmentFlag.AlignCenter, glyph)
            if self.game:
                painter.setFont(QFont("Noto Sans CJK SC", 10, QFont.Weight.DemiBold))
                painter.drawText(
                    self.rect().adjusted(14, 0, -14, -16),
                    Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                    self.game.engine.display_name,
                )
        if self.game:
            badge = QRectF(10, 10, 48, 24)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(10, 16, 28, 170))
            painter.drawRoundedRect(badge, 7, 7)
            painter.setPen(QColor(255, 255, 255, 235))
            painter.setFont(QFont("Noto Sans CJK SC", 8, QFont.Weight.Bold))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.game.engine.abbr)


class GameCard(QWidget):
    clicked = pyqtSignal(object)
    activated = pyqtSignal(object)
    context_requested = pyqtSignal(object, object)
    quick_requested = pyqtSignal(object)
    launch_requested = pyqtSignal(object)

    def __init__(
        self,
        game: Game,
        tr: Translator,
        compact: bool = False,
        title_override: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.game = game
        self.tr = tr
        self.compact = compact
        self.setObjectName("GameCard")
        self.setStyleSheet(
            """
            QWidget#GameCard {
                background: transparent;
                border: none;
            }
            QWidget#GameCard:hover {
                background: rgba(100, 140, 200, 0.07);
                border-radius: 14px;
            }
            """
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(170 if compact else 190, 238 if compact else 276)
        layout = QVBoxLayout(self)
        margin = 6 if compact else 8
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(7)
        self.cover = CoverArt(game)
        layout.addWidget(self.cover, 1)
        self.title_label = QLabel(title_override or game.title)
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(44)
        self.title_label.setStyleSheet("font-weight: 650; font-size: 13px;")
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(self.title_label)
        meta = QLabel(
            f"{game.engine.display_name} · {format_relative_time(game.open_time, tr)}"
        )
        meta.setObjectName("Muted")
        meta.setStyleSheet("font-size: 11px;")
        meta.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(meta)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.game)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.game)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        launch = menu.addAction(self.tr.text("games.launch"))
        quick_label = self.tr.text("games.quick_remove" if self.game.quick_launch else "games.quick")
        quick = menu.addAction(quick_label)
        menu.addSeparator()
        details = menu.addAction(self.tr.text("games.details"))
        menu.addSeparator()
        remove = menu.addAction(self.tr.text("games.delete"))
        action = menu.exec(event.globalPos())
        if action == launch:
            self.launch_requested.emit(self.game)
        elif action == quick:
            self.quick_requested.emit(self.game)
        elif action == details:
            self.clicked.emit(self.game)
        elif action == remove:
            self.context_requested.emit(self.game, "delete")


class ResponsiveGrid(QWidget):
    def __init__(self, card_width: int = 190, spacing: int = 16, parent=None):
        super().__init__(parent)
        self.card_width = card_width
        self.spacing = spacing
        self._items: list[QWidget] = []
        self._columns = 0
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._container = QWidget()
        self._grid = None
        self._layout.addWidget(self._container)
        self._rebuild()

    def set_items(self, widgets: list[QWidget]) -> None:
        self._items = widgets
        self._columns = 0
        self._rebuild()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        columns = max(1, (self.width() + self.spacing) // (self.card_width + self.spacing))
        if columns != self._columns:
            self._columns = columns
            self._rebuild()

    def _rebuild(self) -> None:
        from PyQt6.QtWidgets import QGridLayout

        if self._grid is not None:
            old = self._container.layout()
            if old is not None:
                while old.count():
                    item = old.takeAt(0)
                    if item.widget():
                        item.widget().setParent(None)
            old_container = self._container
            old_container.deleteLater()
        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(self.spacing)
        self._grid.setVerticalSpacing(self.spacing)
        columns = self._columns or 1
        for index, widget in enumerate(self._items):
            self._grid.addWidget(widget, index // columns, index % columns)
        for column in range(max(columns, 1)):
            self._grid.setColumnStretch(column, 1)
        self._layout.addWidget(self._container)


class NavButton(QPushButton):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(f"  {icon}   {label}", parent)
        self.setCheckable(True)
        self.setObjectName("NavButton")
        self.setMinimumHeight(44)


class StatCard(QFrame):
    def __init__(self, label: str, value: str, detail: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        label_widget = QLabel(label)
        label_widget.setObjectName("Muted")
        value_widget = QLabel(value)
        value_widget.setStyleSheet("font-size: 24px; font-weight: 750;")
        detail_widget = QLabel(detail)
        detail_widget.setObjectName("Muted")
        layout.addWidget(label_widget)
        layout.addWidget(value_widget)
        layout.addWidget(detail_widget)


class EngineBanner(QFrame):
    configure = pyqtSignal(str)

    def __init__(self, engine, status, tr: Translator, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumHeight(72)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)
        color = QColor(engine.color)
        icon = QLabel(engine.abbr)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(54, 54)
        icon.setStyleSheet(
            f"background: {color.name()}; color: white; border-radius: 13px; "
            "font-size: 16px; font-weight: 800;"
        )
        layout.addWidget(icon)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        name = QLabel(engine.display_name)
        name.setStyleSheet("font-size: 15px; font-weight: 700;")
        subtitle = QLabel(
            f"{status.name} · {status.executable or tr.text('engines.missing')}"
        )
        subtitle.setObjectName("Muted")
        subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_layout.addWidget(name)
        text_layout.addWidget(subtitle)
        layout.addLayout(text_layout, 1)
        state = QLabel(tr.text("engines.ready" if status.available else "engines.missing"))
        state.setObjectName("Badge")
        if not status.available:
            state.setStyleSheet("color: #B66A3C; background: rgba(214, 123, 65, 0.15); border-radius: 6px; padding: 3px 8px;")
        layout.addWidget(state)
        button = QPushButton(tr.text("engines.configure"))
        button.clicked.connect(lambda: self.configure.emit(status.key))
        layout.addWidget(button)


class EmptyState(QWidget):
    def __init__(self, title: str, detail: str, action: str | None = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 60, 30, 60)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph = QLabel("◇")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph.setStyleSheet("font-size: 54px; color: rgba(100, 140, 210, 0.45);")
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_label = QLabel(detail)
        detail_label.setObjectName("Muted")
        detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_label.setWordWrap(True)
        layout.addWidget(glyph)
        layout.addSpacing(8)
        layout.addWidget(label)
        layout.addWidget(detail_label)
        self.action_button = QPushButton(action or "")
        self.action_button.setObjectName("Primary")
        self.action_button.setVisible(bool(action))
        self.action_button.setFixedWidth(180)
        layout.addSpacing(12)
        layout.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignHCenter)
