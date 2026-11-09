from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import Translator
from ..models import EngineType, Game
from ..qtwebengine import QWEBENGINE_AVAILABLE, QWebEngineView
from ..runtimes import RuntimeManager
from ..settings import COVER_SOURCES, DEFAULT_COVER_ORDER, DEFAULTS, Settings
from .dialogs import (
    ArchiveDialog,
    CoverDialog,
    CoverSourcesDialog,
    GameDetailsDialog,
    GameSettingsDialog,
    PcGameDialog,
    RuntimeDialog,
    SaveManagerDialog,
    UpdateDialog,
    WebDavDialog,
    confirm,
    message,
)
from .theme import palette
from .widgets import (
    CoverArt,
    EmptyState,
    EngineBanner,
    GameCard,
    ResponsiveGrid,
    StatCard,
    display_title,
    format_bytes,
    format_relative_time,
    title_sort_key,
)
from .workers import Worker


def _scrollable(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


def _page_header(title: str, subtitle: str | None = None) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    container.setLayout(layout)
    label = QLabel(title)
    label.setObjectName("PageTitle")
    layout.addWidget(label)
    if subtitle:
        detail = QLabel(subtitle)
        detail.setObjectName("Muted")
        layout.addWidget(detail)
    return container


class HomePage(QWidget):
    open_library = pyqtSignal()
    open_game = pyqtSignal(object)
    launch_game = pyqtSignal(object)

    def __init__(self, window, tr: Translator, settings: Settings):
        super().__init__()
        self.window = window
        self.tr = tr
        self.settings = settings
        self._content = QWidget()
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(30, 24, 30, 32)
        self._layout.setSpacing(20)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(_scrollable(self._content))

    def refresh(self, games: list[Game], recent: list[Game], quick: list[Game]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                _clear_layout(item.layout())
        self._layout.addWidget(
            _page_header(self.tr.text("home.title"), self.tr.text("home.welcome"))
        )
        if self.settings.get("home_mode", "native") == "web":
            self._build_web_home()
            return
        if not games:
            empty = EmptyState(
                self.tr.text("home.empty"),
                self.tr.text("home.open_library"),
                self.tr.text("home.open_library"),
            )
            empty.action_button.clicked.connect(self.open_library.emit)
            self._layout.addWidget(empty)
            return
        latest = recent[0] if recent else games[0]
        self._layout.addWidget(self._hero(latest))
        if quick:
            self._layout.addWidget(self._section_title(self.tr.text("home.quick")))
            self._layout.addWidget(self._card_grid(quick[:3], compact=True))
        self._layout.addWidget(self._section_title(self.tr.text("home.recent")))
        if recent:
            self._layout.addWidget(self._card_grid(recent[:15]))
        else:
            hint = QLabel(self.tr.text("games.never"))
            hint.setObjectName("Muted")
            self._layout.addWidget(hint)
        self._layout.addStretch(1)

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _hero(self, game: Game) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card.setMinimumHeight(196)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(24)
        cover = CoverArt(game)
        cover.setFixedSize(116, 160)
        layout.addWidget(cover)
        text = QVBoxLayout()
        text.setSpacing(7)
        eyebrow = QLabel(game.engine.display_name)
        eyebrow.setObjectName("Badge")
        eyebrow.setMaximumWidth(180)
        title = QLabel(game.title)
        title.setObjectName("HeroTitle")
        title.setWordWrap(True)
        path = QLabel(game.uri)
        path.setObjectName("Muted")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        launch = QPushButton(self.tr.text("games.launch"))
        launch.setObjectName("Primary")
        launch.setFixedWidth(150)
        launch.clicked.connect(lambda: self.launch_game.emit(game))
        details = QPushButton(self.tr.text("games.details"))
        details.clicked.connect(lambda: self.open_game.emit(game))
        buttons = QHBoxLayout()
        buttons.addWidget(launch)
        buttons.addWidget(details)
        buttons.addStretch(1)
        text.addWidget(eyebrow, 0, Qt.AlignmentFlag.AlignLeft)
        text.addWidget(title)
        text.addWidget(path)
        text.addStretch(1)
        text.addLayout(buttons)
        layout.addLayout(text, 1)
        return card

    def _build_web_home(self) -> None:
        webview = None
        if QWEBENGINE_AVAILABLE and QWebEngineView is not None:
            from PyQt6.QtCore import QUrl

            webview = QWebEngineView()
            webview.setUrl(QUrl(str(self.settings.get("home_url", ""))))
            webview.setMinimumHeight(580)
        else:
            webview = QFrame()
            webview.setObjectName("Card")
            layout = QVBoxLayout(webview)
            layout.setContentsMargins(30, 30, 30, 30)
            label = QLabel(self.tr.text("home.web"))
            label.setObjectName("SectionTitle")
            url = QLabel(str(self.settings.get("home_url", "")))
            url.setWordWrap(True)
            url.setObjectName("Muted")
            button = QPushButton(self.tr.text("home.open_web"))
            button.setObjectName("Primary")
            button.clicked.connect(
                lambda: subprocess.Popen(["xdg-open", str(self.settings.get("home_url", ""))])
            )
            layout.addStretch(1)
            layout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(url, 0, Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
            layout.addStretch(1)
        self._layout.addWidget(webview, 1)

    def _card_grid(self, games: list[Game], compact: bool = False) -> QWidget:
        grid = QWidget()
        layout = QGridLayout(grid)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        columns = 5 if not compact else 3
        for index, game in enumerate(games):
            card = GameCard(
                game,
                self.tr,
                compact=compact,
                title_override=display_title(
                    game.title,
                    bool(self.settings.get("hide_title_tags", False)),
                ),
            )
            card.clicked.connect(self.open_game.emit)
            card.activated.connect(self.launch_game.emit)
            card.launch_requested.connect(self.launch_game.emit)
            layout.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            layout.setColumnStretch(column, 1)
        return grid


class LibraryRow(QFrame):
    clicked = pyqtSignal(object)
    activated = pyqtSignal(object)

    def __init__(self, game: Game, tr: Translator, title_override: str | None = None, parent=None):
        super().__init__(parent)
        self.game = game
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(104)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 14, 8)
        cover = CoverArt(game)
        cover.setFixedSize(64, 86)
        layout.addWidget(cover)
        text = QVBoxLayout()
        title = QLabel(title_override or game.title)
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        engine = QLabel(f"{game.engine.display_name} · {format_relative_time(game.open_time, tr)}")
        engine.setObjectName("Muted")
        path = QLabel(game.uri)
        path.setObjectName("Muted")
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.addWidget(title)
        text.addWidget(engine)
        text.addWidget(path)
        text.addStretch(1)
        layout.addLayout(text, 1)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.game)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.game)
        super().mouseDoubleClickEvent(event)


class LibraryPage(QWidget):
    add_folder = pyqtSignal()
    add_pc = pyqtSignal()
    scan = pyqtSignal()
    open_game = pyqtSignal(object)
    launch_game = pyqtSignal(object)
    change_cover = pyqtSignal(object)
    save_manager = pyqtSignal(object)
    game_settings = pyqtSignal(object)
    delete_game = pyqtSignal(object)
    toggle_quick = pyqtSignal(object)
    open_folder = pyqtSignal(object)

    def __init__(self, window, tr: Translator, settings: Settings):
        super().__init__()
        self.window = window
        self.tr = tr
        self.settings = settings
        self._games: list[Game] = []
        self._query = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 24, 30, 26)
        root.setSpacing(14)
        toolbar = QHBoxLayout()
        title_column = _page_header(tr.text("games.title"))
        toolbar.addWidget(title_column)
        toolbar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr.text("games.search"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(250)
        self.search.textChanged.connect(self._filter)
        toolbar.addWidget(self.search)
        self.sort = QComboBox()
        self.sort.addItem("A → Z", "title")
        self.sort.addItem("Recent", "recent")
        self.sort.addItem("Engine", "engine")
        self.sort.setCurrentIndex(max(0, self.sort.findData(settings.get("sort_mode", "title"))))
        self.sort.currentIndexChanged.connect(self._sort_changed)
        toolbar.addWidget(self.sort)
        self.style = QComboBox()
        self.style.addItem(tr.text("games.grid"), "grid")
        self.style.addItem(tr.text("games.list"), "list")
        self.style.setCurrentIndex(max(0, self.style.findData(settings.get("card_style", "grid"))))
        self.style.currentIndexChanged.connect(self._style_changed)
        toolbar.addWidget(self.style)
        add_button = QPushButton(tr.text("games.add"))
        add_button.setObjectName("Primary")
        add_button.clicked.connect(self._add_menu)
        toolbar.addWidget(add_button)
        rescan = QPushButton(tr.text("games.scan"))
        rescan.clicked.connect(self.scan.emit)
        toolbar.addWidget(rescan)
        root.addLayout(toolbar)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        root.addWidget(self.count_label)
        self.stack = QStackedWidget()
        self.empty = EmptyState(
            tr.text("home.empty"),
            tr.text("add.folder_hint"),
            tr.text("games.add_folder"),
        )
        self.empty.action_button.clicked.connect(self.add_folder.emit)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self.content)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.scroll)
        root.addWidget(self.stack, 1)

    def refresh_games(self, games: list[Game]) -> None:
        self._games = games
        self._render()

    def _filter(self, text: str) -> None:
        self._query = text.strip().casefold()
        self._render()

    def _sort_changed(self) -> None:
        self.settings.set("sort_mode", self.sort.currentData())
        self._render()

    def _style_changed(self) -> None:
        self.settings.set("card_style", self.style.currentData())
        self._render()

    def _visible_games(self) -> list[Game]:
        games = [
            game
            for game in self._games
            if not self._query
            or self._query in game.title.casefold()
            or self._query in game.engine.display_name.casefold()
        ]
        mode = self.sort.currentData()
        if mode == "recent":
            return sorted(games, key=lambda game: game.open_time, reverse=True)
        if mode == "engine":
            return sorted(games, key=lambda game: (game.engine.display_name.casefold(), game.title.casefold()))
        ignore_tags = bool(self.settings.get("sort_ignore_tags", False))
        return sorted(games, key=lambda game: title_sort_key(game.title, ignore_tags))

    def _render(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        visible = self._visible_games()
        self.count_label.setText(self.tr.text("games.total", count=len(visible)))
        if not self._games:
            self.stack.setCurrentWidget(self.empty)
            return
        self.stack.setCurrentWidget(self.scroll)
        if not visible:
            label = QLabel(self.tr.text("cover.no_results"))
            label.setObjectName("Muted")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_layout.addWidget(label)
            self.content_layout.addStretch(1)
            return
        if self.style.currentData() == "list":
            for game in visible:
                row = LibraryRow(
                    game,
                    self.tr,
                    display_title(
                        game.title,
                        bool(self.settings.get("hide_title_tags", False)),
                    ),
                )
                row.clicked.connect(self.open_game.emit)
                row.activated.connect(self.launch_game.emit)
                self.content_layout.addWidget(row)
            self.content_layout.addStretch(1)
        else:
            cards = []
            for game in visible:
                card = GameCard(
                    game,
                    self.tr,
                    title_override=display_title(
                        game.title,
                        bool(self.settings.get("hide_title_tags", False)),
                    ),
                )
                card.clicked.connect(self.open_game.emit)
                card.activated.connect(self.launch_game.emit)
                card.launch_requested.connect(self.launch_game.emit)
                card.quick_requested.connect(self.toggle_quick.emit)
                card.context_requested.connect(lambda game, action: self._context_action(game, action))
                cards.append(card)
            grid = ResponsiveGrid()
            grid.set_items(cards)
            self.content_layout.addWidget(grid)
            self.content_layout.addStretch(1)

    def _context_action(self, game: Game, action: str) -> None:
        if action == "delete":
            self.delete_game.emit(game)

    def _add_menu(self) -> None:
        self.add_folder.emit()


class EnginesPage(QWidget):
    configure_runtime = pyqtSignal(str)
    archive_tool = pyqtSignal()

    def __init__(self, window, tr: Translator, settings: Settings, runtimes: RuntimeManager):
        super().__init__()
        self.window = window
        self.tr = tr
        self.settings = settings
        self.runtimes = runtimes
        self._storage_size: int | None = None
        self._storage_signature: tuple[str, ...] = ()
        self._size_worker: Worker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 26)
        header = QHBoxLayout()
        header.addWidget(_page_header(tr.text("engines.title")))
        header.addStretch(1)
        refresh = QPushButton(tr.text("engines.refresh"))
        refresh.clicked.connect(self._refresh_runtimes)
        header.addWidget(refresh)
        archive = QPushButton(tr.text("engines.archive"))
        archive.clicked.connect(self.archive_tool.emit)
        header.addWidget(archive)
        layout.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 4, 0, 10)
        self.content_layout.setSpacing(10)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

    def refresh_engines(self, games: list[Game]) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        statuses = self.runtimes.statuses()
        usage = shutil.disk_usage(Path.home())
        overview = QFrame()
        overview.setObjectName("Card")
        over_layout = QHBoxLayout(overview)
        over_layout.setContentsMargins(20, 16, 20, 16)
        text = QVBoxLayout()
        title = QLabel(self.tr.text("engines.storage"))
        title.setObjectName("SectionTitle")
        text.addWidget(title)
        self.storage_label = QLabel(
            f"{self.tr.text('engines.used')}: "
            f"{format_bytes(self._storage_size) if self._storage_size is not None else '…'}   ·   "
            f"{self.tr.text('engines.free')}: {format_bytes(usage.free)}"
        )
        text.addWidget(self.storage_label)
        visible = self.runtimes.visible_engines()
        available = len(visible)
        text.addWidget(
            QLabel(
                f"{len(games)} {self.tr.text('engines.games')}   ·   "
                f"{available} {self.tr.text('engines.runtime')}"
            )
        )
        over_layout.addLayout(text, 1)
        self.content_layout.addWidget(overview)
        self.content_layout.addWidget(self._section(self.tr.text("engines.runtime")))
        for engine, status in visible:
            banner = EngineBanner(engine, status, self.tr)
            banner.configure.connect(self.configure_runtime.emit)
            self.content_layout.addWidget(banner)
        self.content_layout.addStretch(1)
        signature = tuple(sorted(game.uri for game in games))
        if signature != self._storage_signature and self._size_worker is None:
            self._storage_signature = signature
            worker = Worker(_paths_size, set(signature))
            self._size_worker = worker
            worker.signals.result.connect(self._storage_ready)
            worker.signals.finished.connect(lambda: setattr(self, "_size_worker", None))
            QThreadPool.globalInstance().start(worker)

    def _storage_ready(self, value: int) -> None:
        self._storage_size = value
        if hasattr(self, "storage_label"):
            self.storage_label.setText(
                f"{self.tr.text('engines.used')}: {format_bytes(value)}   ·   "
                f"{self.tr.text('engines.free')}: {format_bytes(shutil.disk_usage(Path.home()).free)}"
            )

    def _refresh_runtimes(self) -> None:
        self.runtimes.refresh()
        self.window.refresh_all()

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        label.setContentsMargins(0, 12, 0, 2)
        return label


class SettingsPage(QWidget):
    add_root = pyqtSignal()
    remove_root = pyqtSignal(str)
    scrape_covers = pyqtSignal()
    cover_sources = pyqtSignal()
    webdav = pyqtSignal()
    logs = pyqtSignal()
    reset = pyqtSignal()
    clean_missing = pyqtSignal()
    language_changed = pyqtSignal()
    theme_changed = pyqtSignal()

    def __init__(self, window, tr: Translator, settings: Settings):
        super().__init__()
        self.window = window
        self.tr = tr
        self.settings = settings
        self._building = False
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(30, 24, 30, 26)
        root_layout.addWidget(_page_header(tr.text("settings.title")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(0, 6, 0, 16)
        self.layout.setSpacing(12)
        scroll.setWidget(content)
        root_layout.addWidget(scroll, 1)
        self._build()

    def _build(self) -> None:
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                _clear_layout(item.layout())
        self._building = True
        self._application_section()
        self._library_section()
        self._covers_section()
        self._save_section()
        self._tools_section()
        self.layout.addStretch(1)
        self._building = False

    def _section_frame(self, title: str) -> tuple[QFrame, QFormLayout]:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 15, 18, 15)
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(10)
        layout.addLayout(form)
        self.layout.addWidget(frame)
        return frame, form

    def _application_section(self) -> None:
        _, form = self._section_frame(self.tr.text("settings.application"))
        language = QComboBox()
        language.addItem("System", "system")
        language.addItem("简体中文", "zh_CN")
        language.addItem("English", "en")
        language.addItem("日本語", "ja")
        language.setCurrentIndex(max(0, language.findData(self.settings.get("language", "zh_CN"))))
        language.currentIndexChanged.connect(lambda: self._set("language", language.currentData(), self.language_changed))
        form.addRow(self.tr.text("settings.language"), language)
        accent = QLineEdit(self.settings.get("accent", "#5B8DEF"))
        accent.editingFinished.connect(lambda: self._set("accent", accent.text(), self.theme_changed, save=True))
        form.addRow(self.tr.text("settings.accent"), accent)
        appearance = QComboBox()
        appearance.addItem("Default", "default")
        appearance.addItem("Retro Glass", "glass")
        appearance.addItem("White Mist", "milk")
        appearance.setCurrentIndex(max(0, appearance.findData(self.settings.get("appearance_style", "default"))))
        appearance.currentIndexChanged.connect(
            lambda: self._set("appearance_style", appearance.currentData(), self.theme_changed, save=True)
        )
        form.addRow(self.tr.text("settings.appearance"), appearance)
        mode = QComboBox()
        mode.addItem("System", "system")
        mode.addItem("Light", "light")
        mode.addItem("Dark", "dark")
        mode.setCurrentIndex(max(0, mode.findData(self.settings.get("appearance_mode", "system"))))
        mode.setEnabled(self.settings.get("appearance_style") == "default")
        mode.currentIndexChanged.connect(
            lambda: self._set("appearance_mode", mode.currentData(), self.theme_changed, save=True)
        )
        form.addRow(self.tr.text("settings.mode"), mode)
        radius = QSpinBox()
        radius.setRange(5, 50)
        radius.setSingleStep(5)
        radius.setValue(int(self.settings.get("corner_radius", 15)))
        radius.valueChanged.connect(
            lambda value: self._set("corner_radius", value, self.theme_changed, save=True)
        )
        form.addRow(self.tr.text("settings.radius"), radius)
        particles = QCheckBox()
        particles.setChecked(bool(self.settings.get("particles", True)))
        particles.toggled.connect(lambda value: self._set("particles", value, self.theme_changed, save=True))
        form.addRow(self.tr.text("settings.particles"), particles)
        home_mode = QComboBox()
        home_mode.addItem("Native", "native")
        home_mode.addItem("Web", "web")
        home_mode.setCurrentIndex(max(0, home_mode.findData(self.settings.get("home_mode", "native"))))
        home_mode.currentIndexChanged.connect(lambda: self._set("home_mode", home_mode.currentData()))
        form.addRow(self.tr.text("settings.home_mode"), home_mode)
        home_url = QLineEdit(self.settings.get("home_url", ""))
        home_url.editingFinished.connect(lambda: self._set("home_url", home_url.text()))
        form.addRow(self.tr.text("settings.home_url"), home_url)
        minimize = QCheckBox()
        minimize.setChecked(bool(self.settings.get("minimize_on_launch", False)))
        minimize.toggled.connect(lambda value: self._set("minimize_on_launch", value))
        form.addRow(self.tr.text("settings.minimize"), minimize)
        close_after = QCheckBox()
        close_after.setChecked(bool(self.settings.get("close_after_launch", False)))
        close_after.toggled.connect(lambda value: self._set("close_after_launch", value))
        form.addRow(self.tr.text("settings.close"), close_after)
        prefix = QLineEdit(self.settings.get("launch_prefix", ""))
        prefix.setPlaceholderText("gamescope -f --   /   gamemoderun")
        prefix.editingFinished.connect(lambda: self._set("launch_prefix", prefix.text().strip()))
        form.addRow("Launch prefix", prefix)

    def _library_section(self) -> None:
        _, form = self._section_frame(self.tr.text("settings.scan"))
        roots_widget = QWidget()
        roots_layout = QVBoxLayout(roots_widget)
        roots_layout.setContentsMargins(0, 0, 0, 0)
        roots = self.window.library.roots()
        for root in roots:
            row = QHBoxLayout()
            path = QLabel(root)
            path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            remove = QPushButton(self.tr.text("common.remove"))
            remove.setObjectName("Danger")
            remove.clicked.connect(lambda checked=False, value=root: self.remove_root.emit(value))
            row.addWidget(path, 1)
            row.addWidget(remove)
            roots_layout.addLayout(row)
        if not roots:
            none = QLabel(self.tr.text("common.none"))
            none.setObjectName("Muted")
            roots_layout.addWidget(none)
        add_root = QPushButton(self.tr.text("games.add_folder"))
        add_root.clicked.connect(self.add_root.emit)
        roots_layout.addWidget(add_root)
        form.addRow("Scan roots", roots_widget)
        depth = QSpinBox()
        depth.setRange(1, 8)
        depth.setValue(int(self.settings.get("scan_depth", 3)))
        depth.valueChanged.connect(lambda value: self._set("scan_depth", value))
        form.addRow(self.tr.text("settings.depth"), depth)
        sort = QComboBox()
        sort.addItem("A → Z", "title")
        sort.addItem("Recent", "recent")
        sort.addItem("Engine", "engine")
        sort.setCurrentIndex(max(0, sort.findData(self.settings.get("sort_mode", "title"))))
        sort.currentIndexChanged.connect(lambda: self._set("sort_mode", sort.currentData()))
        form.addRow(self.tr.text("settings.sort"), sort)
        style = QComboBox()
        style.addItem(self.tr.text("games.grid"), "grid")
        style.addItem(self.tr.text("games.list"), "list")
        style.setCurrentIndex(max(0, style.findData(self.settings.get("card_style", "grid"))))
        style.currentIndexChanged.connect(lambda: self._set("card_style", style.currentData()))
        form.addRow(self.tr.text("settings.card"), style)
        ignore_tags = QCheckBox("Sort by title without bracket tags")
        ignore_tags.setChecked(bool(self.settings.get("sort_ignore_tags", False)))
        ignore_tags.toggled.connect(lambda value: self._set("sort_ignore_tags", value))
        form.addRow("", ignore_tags)
        hide_tags = QCheckBox("Hide bracket tags on cards")
        hide_tags.setChecked(bool(self.settings.get("hide_title_tags", False)))
        hide_tags.toggled.connect(lambda value: self._set("hide_title_tags", value))
        form.addRow("", hide_tags)
        clean = QPushButton(self.tr.text("settings.clean_missing"))
        clean.setObjectName("Danger")
        clean.clicked.connect(self.clean_missing.emit)
        form.addRow("", clean)

    def _covers_section(self) -> None:
        _, form = self._section_frame(self.tr.text("settings.covers"))
        sources = QPushButton(self.tr.text("settings.cover_sources"))
        sources.clicked.connect(self.cover_sources.emit)
        form.addRow(self.tr.text("settings.cover_sources"), sources)
        only = QCheckBox(self.tr.text("settings.only_missing"))
        only.setChecked(bool(self.settings.get("cover_only_missing", True)))
        only.toggled.connect(lambda value: self._set("cover_only_missing", value))
        form.addRow("", only)
        large = QCheckBox("VNDB large covers")
        large.setChecked(bool(self.settings.get("vndb_large_cover", True)))
        large.toggled.connect(lambda value: self._set("vndb_large_cover", value))
        form.addRow("", large)
        scrape = QPushButton(self.tr.text("settings.scrape_all"))
        scrape.setObjectName("Primary")
        scrape.clicked.connect(self.scrape_covers.emit)
        form.addRow("", scrape)

    def _save_section(self) -> None:
        _, form = self._section_frame(self.tr.text("settings.save"))
        button = QPushButton(self.tr.text("settings.webdav"))
        button.clicked.connect(self.webdav.emit)
        state = (
            self.tr.text("engines.ready")
            if self.settings.get("save_sync_enabled", False)
            else self.tr.text("engines.missing")
        )
        form.addRow(button, QLabel(state))

    def _tools_section(self) -> None:
        _, form = self._section_frame(self.tr.text("settings.tools"))
        archive = QPushButton(self.tr.text("engines.archive"))
        archive.clicked.connect(lambda: ArchiveDialog(self.tr, self).exec())
        form.addRow(archive)
        logs = QPushButton(self.tr.text("settings.logs"))
        logs.clicked.connect(self.logs.emit)
        form.addRow(logs)
        updates = QPushButton("Check for updates")
        updates.clicked.connect(lambda: UpdateDialog(self.tr, self).exec())
        form.addRow(updates)
        about = QPushButton(self.tr.text("settings.about"))
        about.clicked.connect(self._about)
        form.addRow(about)
        reset = QPushButton(self.tr.text("settings.reset"))
        reset.setObjectName("Danger")
        reset.clicked.connect(self.reset.emit)
        form.addRow(reset)

    def _about(self) -> None:
        message(
            self,
            self.tr.text("settings.about"),
            "Tyranor Next Linux 1.0.0\n\nNative Linux desktop port.\n"
            "GPL-2.0-only · Built with PyQt6 and SQLite.",
        )

    def _set(self, key: str, value, signal=None, save: bool = True) -> None:
        if self._building:
            return
        self.settings.set(key, value, persist=save)
        if signal is not None:
            signal.emit()
        self.window.data_changed()


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _paths_size(paths: set[str]) -> int:
    total = 0
    seen: set[Path] = set()
    for value in paths:
        path = Path(value)
        if path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            if path.is_file():
                total += path.stat().st_size
                continue
            for root, dirs, files in os.walk(path):
                dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
                for name in files:
                    try:
                        total += (Path(root) / name).stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total
