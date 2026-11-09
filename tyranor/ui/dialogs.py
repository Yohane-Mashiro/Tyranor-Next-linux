from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl

from ..archive import ArchiveError, ArchiveTool
from ..covers import CoverError, CoverService, clean_title
from ..i18n import Translator
from ..hikarinagi import HikarinagiAuth
from ..launcher import Launcher
from ..models import Candidate, EngineType, Game
from ..patches import PatchEntry, PatchError, fetch_index, install as install_patch, search as search_patches
from ..launcher import split_args
from ..runtimes import RUNTIMES, RuntimeManager
from ..rpg_saves import RpgSaveError, convert_to_tyranor, export_to_standard
from ..saves import SaveError, SaveManager
from ..secrets import SecretStore
from ..settings import COVER_SOURCES, DEFAULT_COVER_ORDER, Settings
from ..updater import check_updates
from ..webdav import WebDavError, WebDavSync
from .theme import palette
from .widgets import CoverArt, format_bytes
from .workers import Worker, start_worker


def message(parent: QWidget, title: str, text: str, error: bool = False) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Critical if error else QMessageBox.Icon.Information)
    box.exec()


def confirm(parent: QWidget, title: str, text: str) -> bool:
    return (
        QMessageBox.question(
            parent,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes
    )


class OnboardingDialog(QDialog):
    page_requested = pyqtSignal(int)

    def __init__(self, tr: Translator, settings: Settings, parent=None):
        super().__init__(parent)
        self.tr = tr
        self.settings = settings
        self.step = 0
        self.setWindowTitle("Tyranor Next Linux")
        self.setModal(True)
        self.resize(620, 390)
        self.setStyleSheet("QDialog { background: palette(base); }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 26)
        self.counter = QLabel()
        self.counter.setObjectName("Muted")
        self.title_label = QLabel()
        self.title_label.setObjectName("PageTitle")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setObjectName("Muted")
        self.body.setStyleSheet("font-size: 16px; line-height: 1.5;")
        layout.addWidget(self.counter)
        layout.addSpacing(24)
        layout.addWidget(self.title_label)
        layout.addSpacing(12)
        layout.addWidget(self.body)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        self.skip = QPushButton(tr.text("common.skip"))
        self.back = QPushButton(tr.text("common.back"))
        self.next = QPushButton(tr.text("common.next"))
        self.next.setObjectName("Primary")
        self.skip.clicked.connect(self._finish)
        self.back.clicked.connect(self._previous)
        self.next.clicked.connect(self._next)
        buttons.addWidget(self.skip)
        buttons.addStretch(1)
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        layout.addLayout(buttons)
        self._show_step()

    def _show_step(self) -> None:
        self.counter.setText(f"{self.step + 1} / 7")
        self.title_label.setText(self.tr.text(f"onboarding.{self.step + 1}.title"))
        self.body.setText(self.tr.text(f"onboarding.{self.step + 1}.body"))
        self.back.setEnabled(self.step > 0)
        self.next.setText(
            self.tr.text("common.finish") if self.step == 6 else self.tr.text("common.next")
        )
        page = min(3, self.step * 3 // 7)
        self.page_requested.emit(page)

    def _previous(self) -> None:
        if self.step > 0:
            self.step -= 1
            self._show_step()

    def _next(self) -> None:
        if self.step >= 6:
            self._finish()
            return
        self.step += 1
        self._show_step()

    def _finish(self) -> None:
        self.settings.set("onboarding_done", True)
        self.accept()


class RuntimeDialog(QDialog):
    def __init__(self, manager: RuntimeManager, key: str, tr: Translator, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.key = key
        self.tr = tr
        status = manager.statuses()[key]
        self.setWindowTitle(tr.text("runtime.title", name=status.name))
        self.resize(650, 310)
        layout = QVBoxLayout(self)
        description = QLabel(status.description)
        description.setWordWrap(True)
        description.setObjectName("Muted")
        layout.addWidget(description)
        if status.homepage:
            project = QPushButton("Open project page")
            project.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(status.homepage))
            )
            layout.addWidget(project, 0, Qt.AlignmentFlag.AlignLeft)
        form = QFormLayout()
        self.program = QLineEdit(status.executable or "")
        browse = QPushButton(tr.text("common.browse"))
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.program, 1)
        row.addWidget(browse)
        form.addRow(tr.text("runtime.program"), row)
        self.args = QLineEdit(" ".join(status.args) if status.args else "{path}")
        form.addRow(tr.text("runtime.args"), self.args)
        self.env = QTextEdit()
        self.env.setPlaceholderText("KEY=VALUE\nSDL_VIDEODRIVER=x11")
        self.env.setMaximumHeight(90)
        self.env.setPlainText("\n".join(f"{key}={value}" for key, value in status.env.items()))
        form.addRow("Environment", self.env)
        layout.addLayout(form)
        help_label = QLabel(tr.text("runtime.args_help"))
        help_label.setObjectName("Muted")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        reset = QPushButton(tr.text("runtime.reset"))
        reset.clicked.connect(self._reset)
        cancel = QPushButton(tr.text("common.cancel"))
        save = QPushButton(tr.text("common.save"))
        save.setObjectName("Primary")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr.text("runtime.program"), str(Path.home()))
        if path:
            self.program.setText(path)

    def _save(self) -> None:
        self.manager.set_override(
            self.key,
            self.program.text(),
            split_args(self.args.text()),
            _parse_env(self.env.toPlainText()),
        )
        self.accept()

    def _reset(self) -> None:
        self.manager.clear_override(self.key)
        self.accept()


class CandidateRow(QWidget):
    def __init__(self, candidate: Candidate, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.image = QLabel()
        self.image.setFixedSize(66, 92)
        self.image.setStyleSheet("background: #334155; border-radius: 7px;")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setText("…")
        layout.addWidget(self.image)
        text = QVBoxLayout()
        title = QLabel(candidate.title or "(untitled)")
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        subtitle = QLabel(candidate.subtitle)
        subtitle.setObjectName("Muted")
        detail = QLabel(candidate.detail)
        detail.setObjectName("Muted")
        detail.setStyleSheet("font-size: 11px;")
        text.addWidget(title)
        text.addWidget(subtitle)
        text.addWidget(detail)
        text.addStretch(1)
        layout.addLayout(text, 1)


class CoverDialog(QDialog):
    def __init__(
        self,
        game: Game,
        service: CoverService,
        tr: Translator,
        parent=None,
    ):
        super().__init__(parent)
        self.game = game
        self.service = service
        self.tr = tr
        self.candidates: list[Candidate] = []
        self.pool = QThreadPool.globalInstance()
        self.setWindowTitle(tr.text("cover.title"))
        self.resize(760, 590)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.source = QComboBox()
        for key in service.enabled_sources():
            self.source.addItem(COVER_SOURCES[key], key)
        self.keyword = QLineEdit(clean_title(game.title))
        self.keyword.setPlaceholderText(tr.text("cover.keyword"))
        search = QPushButton(tr.text("cover.search"))
        search.setObjectName("Primary")
        search.clicked.connect(self._search)
        controls.addWidget(QLabel(tr.text("cover.source")))
        controls.addWidget(self.source)
        controls.addWidget(self.keyword, 1)
        controls.addWidget(search)
        layout.addLayout(controls)
        self.status = QLabel(tr.text("cover.no_results"))
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda _: self._bind())
        layout.addWidget(self.results, 1)
        bottom = QHBoxLayout()
        local = QPushButton(tr.text("cover.local"))
        more = QPushButton(tr.text("cover.more"))
        bind = QPushButton(tr.text("cover.bind"))
        bind.setObjectName("Primary")
        local.clicked.connect(self._local)
        more.clicked.connect(self._more_covers)
        bind.clicked.connect(self._bind)
        bottom.addWidget(local)
        bottom.addWidget(more)
        bottom.addStretch(1)
        bottom.addWidget(bind)
        layout.addLayout(bottom)
        self.keyword.returnPressed.connect(self._search)
        QTimer.singleShot(100, self._search)

    def _search(self) -> None:
        source = self.source.currentData()
        if not source:
            return
        self.status.setText(self.tr.text("common.working"))
        worker = Worker(self.service.search, source, self.keyword.text(), 8)
        worker.signals.result.connect(self._show_results)
        worker.signals.error.connect(self._search_error)
        start_worker(self, worker)

    def _show_results(self, candidates: list[Candidate]) -> None:
        self.candidates = candidates
        self.results.clear()
        for candidate in candidates:
            item = QListWidgetItem()
            item.setSizeHint(QSize(600, 108))
            item.setData(Qt.ItemDataRole.UserRole, candidate)
            self.results.addItem(item)
            self.results.setItemWidget(item, CandidateRow(candidate))
            self._load_preview(candidate, item)
        self.status.setText(
            f"{len(candidates)} candidates" if candidates else self.tr.text("cover.no_results")
        )

    def _load_preview(self, candidate: Candidate, item: QListWidgetItem) -> None:
        def fetch():
            response = self.service.session.get(candidate.cover_url, timeout=(8, 20))
            return response.content if response.status_code == 200 else b""

        worker = Worker(fetch)

        def apply(data: bytes) -> None:
            widget = self.results.itemWidget(item)
            if widget and data:
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    widget.image.setPixmap(
                        pixmap.scaled(
                            widget.image.size(),
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )

        worker.signals.result.connect(apply)
        start_worker(self, worker)

    def _search_error(self, text: str) -> None:
        self.status.setText(self.tr.text("cover.search_failed"))
        message(self, self.tr.text("cover.search_failed"), text, True)

    def _selected(self) -> Candidate | None:
        item = self.results.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _bind(self) -> None:
        candidate = self._selected()
        if candidate is None:
            return
        self.status.setText(self.tr.text("common.working"))
        worker = Worker(self.service.download, self.game, candidate)
        worker.signals.result.connect(lambda game: self.accept())
        worker.signals.error.connect(
            lambda text: message(self, self.tr.text("cover.search_failed"), text, True)
        )
        start_worker(self, worker)

    def _more_covers(self) -> None:
        candidate = self._selected()
        if candidate is None or candidate.source != "nextmoe":
            return
        worker = Worker(self.service.list_covers, candidate, 100)
        worker.signals.result.connect(self._show_results)
        worker.signals.error.connect(
            lambda text: message(self, self.tr.text("cover.search_failed"), text, True)
        )
        start_worker(self, worker)

    def _local(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr.text("cover.local"),
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        try:
            self.service.save_custom(self.game, Path(path))
            self.accept()
        except CoverError as exc:
            message(self, self.tr.text("cover.search_failed"), str(exc), True)


class GameDetailsDialog(QDialog):
    action_requested = pyqtSignal(str)
    saved = pyqtSignal()

    def __init__(
        self,
        game: Game,
        launcher: Launcher,
        tr: Translator,
        parent=None,
    ):
        super().__init__(parent)
        self.game = game
        self.launcher = launcher
        self.tr = tr
        self.setWindowTitle(game.title)
        self.resize(700, 500)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(22)
        self.cover = CoverArt(game)
        self.cover.setFixedSize(230, 330)
        layout.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)
        right = QVBoxLayout()
        title = QLabel(game.title)
        title.setObjectName("PageTitle")
        title.setWordWrap(True)
        right.addWidget(title)
        engine = QLabel(f"{game.engine.display_name} · {game.engine.abbr}")
        engine.setObjectName("Badge")
        engine.setMaximumWidth(220)
        right.addWidget(engine, 0, Qt.AlignmentFlag.AlignLeft)
        path_label = QLabel(game.uri)
        path_label.setObjectName("Muted")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(path_label)
        right.addSpacing(8)
        launch = QPushButton(tr.text("games.launch"))
        launch.setObjectName("Primary")
        launch.setMinimumHeight(44)
        launch.clicked.connect(self._launch)
        right.addWidget(launch)
        if self.launcher.running.get(game.uri) and self.launcher.running[game.uri].process.poll() is None:
            launch.setText(tr.text("games.stop"))
            launch.setObjectName("Danger")
            launch.clicked.disconnect()
            launch.clicked.connect(self._stop)
        actions = [
            ("launch_file", "games.launch_file"),
            ("cover", "games.search_cover"),
            ("saves", "games.saves"),
            ("patch", "games.patch"),
            ("settings", "games.settings"),
            ("rename", "games.rename"),
            ("shortcut", "games.shortcut"),
            ("game_log", "games.log"),
            ("folder", "games.open_folder"),
            ("delete", "games.delete"),
        ]
        if game.engine is not EngineType.KIRIKIRI:
            actions = [item for item in actions if item[0] != "patch"]
        action_grid = QHBoxLayout()
        left_actions = QVBoxLayout()
        right_actions = QVBoxLayout()
        for index, (key, label) in enumerate(actions):
            button = QPushButton(tr.text(label))
            button.clicked.connect(lambda checked=False, k=key: self.action_requested.emit(k))
            (left_actions if index % 2 == 0 else right_actions).addWidget(button)
        action_grid.addLayout(left_actions)
        action_grid.addLayout(right_actions)
        right.addLayout(action_grid)
        right.addStretch(1)
        layout.addLayout(right, 1)

    def _launch(self) -> None:
        result = self.launcher.launch(self.game)
        if not result.ok:
            message(self, self.tr.text("toast.launch_failed"), result.message, True)
        else:
            self.accept()

    def _stop(self) -> None:
        self.launcher.stop(self.game)
        self.accept()


class SaveManagerDialog(QDialog):
    def __init__(
        self,
        game: Game,
        saves: SaveManager,
        tr: Translator,
        parent=None,
        webdav: WebDavSync | None = None,
    ):
        super().__init__(parent)
        self.game = game
        self.saves = saves
        self.tr = tr
        self.webdav = webdav
        self.pool = QThreadPool.globalInstance()
        self.setWindowTitle(tr.text("saves.title"))
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        top = QFrame()
        top.setObjectName("Card")
        top_layout = QVBoxLayout(top)
        self.location_label = QLabel()
        self.location_label.setWordWrap(True)
        self.location_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top_layout.addWidget(QLabel(tr.text("saves.location")))
        top_layout.addWidget(self.location_label)
        location_buttons = QHBoxLayout()
        open_button = QPushButton(tr.text("saves.open"))
        change_button = QPushButton(tr.text("saves.change_dir"))
        open_button.clicked.connect(self._open_folder)
        change_button.clicked.connect(self._change_folder)
        location_buttons.addWidget(open_button)
        location_buttons.addWidget(change_button)
        location_buttons.addStretch(1)
        top_layout.addLayout(location_buttons)
        layout.addWidget(top)
        actions = QHBoxLayout()
        for key, label in (
            ("backup", "saves.backup"),
            ("import", "saves.import"),
            ("export", "saves.export"),
            ("clear", "saves.clear"),
        ):
            button = QPushButton(tr.text(label))
            if key == "backup":
                button.setObjectName("Primary")
            button.clicked.connect(lambda checked=False, k=key: self._action(k))
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addWidget(QLabel(tr.text("saves.versions")))
        self.versions = QListWidget()
        layout.addWidget(self.versions, 1)
        self.cloud_versions = QListWidget()
        self.cloud_versions.setVisible(webdav is not None)
        if webdav is not None:
            layout.addWidget(QLabel("Cloud versions"))
            layout.addWidget(self.cloud_versions)
        cloud_actions = QHBoxLayout()
        self.refresh_cloud = QPushButton("Refresh cloud versions")
        self.download_cloud = QPushButton("Download cloud version")
        self.refresh_cloud.setVisible(webdav is not None)
        self.download_cloud.setVisible(webdav is not None)
        self.refresh_cloud.clicked.connect(self._refresh_cloud)
        self.download_cloud.clicked.connect(self._download_cloud)
        cloud_actions.addWidget(self.refresh_cloud)
        cloud_actions.addWidget(self.download_cloud)
        cloud_actions.addStretch(1)
        layout.addLayout(cloud_actions)
        if self.game.engine in {EngineType.RPG_MV, EngineType.RPG_MZ}:
            rpg_actions = QHBoxLayout()
            import_pc = QPushButton("Import PC save format")
            export_pc = QPushButton("Export PC save format")
            import_pc.clicked.connect(self._import_pc_saves)
            export_pc.clicked.connect(self._export_pc_saves)
            rpg_actions.addWidget(import_pc)
            rpg_actions.addWidget(export_pc)
            rpg_actions.addStretch(1)
            layout.addLayout(rpg_actions)
        bottom = QHBoxLayout()
        self.restore = QPushButton(tr.text("saves.restore"))
        delete = QPushButton(tr.text("common.delete"))
        close = QPushButton(tr.text("common.close"))
        self.restore.clicked.connect(self._restore)
        delete.clicked.connect(self._delete_version)
        close.clicked.connect(self.accept)
        bottom.addWidget(self.restore)
        bottom.addWidget(delete)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self._refresh()

    def _refresh(self) -> None:
        location = self.saves.resolve(self.game)
        self.location_label.setText(
            str(location.path) if location else self.tr.text("saves.no_location")
        )
        self.versions.clear()
        for version in self.saves.versions(self.game):
            stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(version.created_at / 1000))
            item = QListWidgetItem(f"{stamp}  ·  {version.source}  ·  {version.content_hash[:12]}")
            item.setData(Qt.ItemDataRole.UserRole, version.version_id)
            self.versions.addItem(item)

    def _action(self, key: str) -> None:
        try:
            if key == "backup":
                self.saves.create_version(self.game)
                self._refresh()
            elif key == "import":
                path, _ = QFileDialog.getOpenFileName(
                    self, self.tr.text("saves.import"), str(Path.home()), "ZIP (*.zip)"
                )
                if path:
                    self.saves.import_zip(self.game, Path(path))
                    self._refresh()
            elif key == "export":
                default = Path.home() / f"{self.game.title}.zip"
                path, _ = QFileDialog.getSaveFileName(
                    self, self.tr.text("saves.export"), str(default), "ZIP (*.zip)"
                )
                if path:
                    self.saves.export_zip(self.game, Path(path))
                    self._refresh()
            elif key == "clear" and confirm(
                self, self.tr.text("common.confirm"), self.tr.text("saves.clear")
            ):
                self.saves.clear_saves(self.game)
        except SaveError as exc:
            message(self, self.tr.text("common.error"), str(exc), True)

    def _open_folder(self) -> None:
        location = self.saves.resolve(self.game)
        if location:
            subprocess.Popen(["xdg-open", str(location.path)])

    def _change_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr.text("saves.change_dir"), str(Path.home()))
        if path:
            self.saves.configure(self.game, Path(path))
            self._refresh()

    def _selected_version(self) -> str | None:
        item = self.versions.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _restore(self) -> None:
        version = self._selected_version()
        if not version:
            return
        if not confirm(self, self.tr.text("common.confirm"), self.tr.text("saves.restore")):
            return
        try:
            self.saves.restore_version(self.game, version)
            self._refresh()
        except SaveError as exc:
            message(self, self.tr.text("common.error"), str(exc), True)

    def _delete_version(self) -> None:
        version = self._selected_version()
        if version and confirm(self, self.tr.text("common.confirm"), self.tr.text("common.delete")):
            self.saves.delete_version(self.game, version)
            self._refresh()

    def _import_pc_saves(self) -> None:
        try:
            result = convert_to_tyranor(self.game)
            message(
                self,
                self.tr.text("common.done"),
                f"Imported: {result.imported}\nSkipped: {result.skipped}\nFailed: {result.failed}",
            )
            self._refresh()
        except (RpgSaveError, OSError) as exc:
            message(self, self.tr.text("common.error"), str(exc), True)

    def _export_pc_saves(self) -> None:
        try:
            result = export_to_standard(self.game)
            message(
                self,
                self.tr.text("common.done"),
                f"Exported: {result.exported}\nSkipped: {result.skipped}\nFailed: {result.failed}",
            )
            self._refresh()
        except OSError as exc:
            message(self, self.tr.text("common.error"), str(exc), True)

    def _refresh_cloud(self) -> None:
        if self.webdav is None:
            return
        worker = Worker(self.webdav.list_versions, self.game)

        def show(versions) -> None:
            self.cloud_versions.clear()
            for version in versions:
                item = QListWidgetItem(f"{version.name}   ·   {format_bytes(version.size)}")
                item.setData(Qt.ItemDataRole.UserRole, version)
                self.cloud_versions.addItem(item)

        worker.signals.result.connect(show)
        worker.signals.error.connect(
            lambda text: message(self, self.tr.text("common.error"), text, True)
        )
        start_worker(self, worker)

    def _download_cloud(self) -> None:
        if self.webdav is None:
            return
        item = self.cloud_versions.currentItem()
        if item is None:
            return
        worker = Worker(self.webdav.download_version, self.game, item.data(Qt.ItemDataRole.UserRole))
        worker.signals.result.connect(lambda _: self._refresh())
        worker.signals.error.connect(
            lambda text: message(self, self.tr.text("common.error"), text, True)
        )
        start_worker(self, worker)


class WebDavDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        webdav: WebDavSync,
        games: list[Game],
        tr: Translator,
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.webdav = webdav
        self.secrets = SecretStore()
        self.games = games
        self.tr = tr
        self.pool = QThreadPool.globalInstance()
        self.setWindowTitle(tr.text("webdav.title"))
        self.resize(720, 620)
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox(tr.text("webdav.enabled"))
        self.enabled.setChecked(bool(settings.get("save_sync_enabled", False)))
        layout.addWidget(self.enabled)
        form = QFormLayout()
        self.url = QLineEdit(settings.get("save_sync_url", ""))
        self.username = QLineEdit(settings.get("save_sync_username", ""))
        self.password = QLineEdit(self.secrets.get("webdav_password", ""))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(tr.text("webdav.url"), self.url)
        form.addRow(tr.text("webdav.username"), self.username)
        form.addRow(tr.text("webdav.password"), self.password)
        layout.addLayout(form)
        row = QHBoxLayout()
        test = QPushButton(tr.text("webdav.test"))
        test.clicked.connect(self._test)
        row.addWidget(test)
        row.addStretch(1)
        layout.addLayout(row)
        direction_row = QFormLayout()
        self.direction = QComboBox()
        for key, label in (
            ("bidirectional", "webdav.bidirectional"),
            ("upload", "webdav.upload"),
            ("download", "webdav.download"),
        ):
            self.direction.addItem(tr.text(label), key)
        index = self.direction.findData(settings.get("save_sync_mode", "bidirectional"))
        self.direction.setCurrentIndex(max(0, index))
        direction_row.addRow(tr.text("webdav.direction"), self.direction)
        self.retention = QSpinBox()
        self.retention.setRange(0, 100)
        self.retention.setValue(int(settings.get("save_sync_retention", 10)))
        direction_row.addRow(tr.text("webdav.retention"), self.retention)
        layout.addLayout(direction_row)
        self.feedback = QCheckBox(tr.text("webdav.feedback"))
        self.feedback.setChecked(bool(settings.get("save_sync_feedback", True)))
        layout.addWidget(self.feedback)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.results = QTextEdit()
        self.results.setReadOnly(True)
        layout.addWidget(self.results, 1)
        buttons = QHBoxLayout()
        sync_all = QPushButton(tr.text("webdav.sync_all"))
        sync_all.clicked.connect(self._sync_all)
        save = QPushButton(tr.text("common.save"))
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        cancel = QPushButton(tr.text("common.cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(sync_all)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _save(self) -> None:
        self.settings.update(
            {
                "save_sync_enabled": self.enabled.isChecked(),
                "save_sync_url": self.url.text().strip(),
                "save_sync_username": self.username.text().strip(),
                "save_sync_mode": self.direction.currentData(),
                "save_sync_retention": self.retention.value(),
                "save_sync_feedback": self.feedback.isChecked(),
            }
        )
        self.secrets.set("webdav_password", self.password.text())
        self.accept()

    def _test(self) -> None:
        self.progress.show()
        worker = Worker(
            self.webdav.test_connection,
            self.url.text(),
            self.username.text(),
            self.password.text(),
        )
        worker.signals.result.connect(self._append)
        worker.signals.error.connect(lambda text: self._append("ERROR: " + text))
        worker.signals.finished.connect(self.progress.hide)
        start_worker(self, worker)

    def _sync_all(self) -> None:
        self._save()
        if not self.webdav.configured():
            message(self, self.tr.text("common.error"), self.tr.text("webdav.enabled"), True)
            return
        self.progress.show()
        self.results.clear()
        worker = Worker(self.webdav.sync_all, self.games, self.settings.get("save_sync_mode", "bidirectional"))
        worker.signals.result.connect(self._show_sync_results)
        worker.signals.error.connect(lambda text: self._append("ERROR: " + text))
        worker.signals.finished.connect(self.progress.hide)
        start_worker(self, worker)

    def _show_sync_results(self, results: list[tuple[Game, str]]) -> None:
        for game, text in results:
            self._append(f"{game.title}: {text}")

    def _append(self, text: str) -> None:
        self.results.append(text)


class ArchiveDialog(QDialog):
    def __init__(self, tr: Translator, parent=None):
        super().__init__(parent)
        self.tr = tr
        self.tool = ArchiveTool()
        self.pool = QThreadPool.globalInstance()
        self.setWindowTitle(tr.text("archive.title"))
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.extract_tab = QWidget()
        self.pack_tab = QWidget()
        self.tabs.addTab(self.extract_tab, tr.text("archive.extract"))
        self.tabs.addTab(self.pack_tab, tr.text("archive.pack"))
        layout.addWidget(self.tabs, 1)
        self._build_extract()
        self._build_pack()
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        status_row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.archive_cancel = QPushButton(tr.text("common.cancel"))
        self.archive_cancel.hide()
        self.archive_cancel.clicked.connect(self.tool.cancel)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.archive_cancel)
        layout.addLayout(status_row)
        close = QPushButton(tr.text("common.close"))
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def _build_extract(self) -> None:
        layout = QVBoxLayout(self.extract_tab)
        row = QHBoxLayout()
        self.extract_source = QLineEdit()
        browse = QPushButton(self.tr.text("common.browse"))
        browse.clicked.connect(self._choose_extract_source)
        row.addWidget(self.extract_source, 1)
        row.addWidget(browse)
        layout.addWidget(QLabel(self.tr.text("archive.source")))
        layout.addLayout(row)
        self.extract_output = QLineEdit()
        output_button = QPushButton(self.tr.text("common.browse"))
        output_button.clicked.connect(self._choose_extract_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.extract_output, 1)
        output_row.addWidget(output_button)
        layout.addWidget(QLabel(self.tr.text("archive.output")))
        layout.addLayout(output_row)
        self.archive_list = QListWidget()
        self.archive_list.itemDoubleClicked.connect(
            lambda item: self._preview_archive(Path(item.text()))
        )
        layout.addWidget(self.archive_list, 1)
        buttons = QHBoxLayout()
        scan = QPushButton(self.tr.text("archive.scan"))
        start = QPushButton(self.tr.text("archive.start"))
        start.setObjectName("Primary")
        scan.clicked.connect(self._scan)
        start.clicked.connect(self._extract)
        buttons.addWidget(scan)
        buttons.addStretch(1)
        buttons.addWidget(start)
        layout.addLayout(buttons)

    def _build_pack(self) -> None:
        layout = QVBoxLayout(self.pack_tab)
        self.pack_source = QLineEdit()
        source_button = QPushButton(self.tr.text("common.browse"))
        source_button.clicked.connect(self._choose_pack_source)
        source_row = QHBoxLayout()
        source_row.addWidget(self.pack_source, 1)
        source_row.addWidget(source_button)
        layout.addWidget(QLabel(self.tr.text("archive.source")))
        layout.addLayout(source_row)
        self.pack_output = QLineEdit()
        output_button = QPushButton(self.tr.text("common.browse"))
        output_button.clicked.connect(self._choose_pack_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.pack_output, 1)
        output_row.addWidget(output_button)
        layout.addWidget(QLabel(self.tr.text("archive.output")))
        layout.addLayout(output_row)
        level_row = QHBoxLayout()
        level_row.addWidget(QLabel(self.tr.text("archive.level")))
        self.level = QSpinBox()
        self.level.setRange(0, 9)
        self.level.setValue(6)
        level_row.addWidget(self.level)
        level_row.addStretch(1)
        layout.addLayout(level_row)
        layout.addStretch(1)
        start = QPushButton(self.tr.text("archive.start"))
        start.setObjectName("Primary")
        start.clicked.connect(self._pack)
        layout.addWidget(start)

    def _choose_extract_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr.text("archive.source"), str(Path.home()))
        if path:
            self.extract_source.setText(path)
            self._scan()

    def _choose_extract_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr.text("archive.output"), str(Path.home()))
        if path:
            self.extract_output.setText(path)

    def _choose_pack_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr.text("archive.source"), str(Path.home()))
        if path:
            self.pack_source.setText(path)

    def _choose_pack_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr.text("archive.output"), str(Path.home() / "data.xp3"), "XP3 (*.xp3)"
        )
        if path:
            self.pack_output.setText(path)

    def _scan(self) -> None:
        root = Path(self.extract_source.text())
        if not root.is_dir():
            return
        worker = Worker(self.tool.scan, root)
        worker.signals.result.connect(self._show_archives)
        worker.signals.error.connect(lambda text: message(self, self.tr.text("common.error"), text, True))
        start_worker(self, worker)

    def _show_archives(self, archives: list[Path]) -> None:
        self.archive_list.clear()
        for path in archives:
            self.archive_list.addItem(str(path))
        self.status.setText(f"{len(archives)} XP3")

    def _preview_archive(self, archive: Path) -> None:
        if not archive.is_file():
            return
        worker = Worker(self.tool.list, archive)

        def show(entries) -> None:
            self.archive_list.clear()
            for name, size, is_directory in entries:
                label = f"{name}/" if is_directory else f"{name}   ·   {format_bytes(size)}"
                self.archive_list.addItem(label)
            self.status.setText(f"{archive.name}: {len(entries)} entries")

        worker.signals.result.connect(show)
        worker.signals.error.connect(
            lambda text: message(self, self.tr.text("common.error"), text, True)
        )
        start_worker(self, worker)

    def _extract(self) -> None:
        root = Path(self.extract_source.text())
        output = Path(self.extract_output.text()) if self.extract_output.text() else None
        if not root.is_dir():
            return
        self.progress.show()
        self.archive_cancel.show()
        self.progress.setRange(0, 0)
        worker = Worker(self.tool.extract_all, root, output, on_progress=self._progress)
        worker.signals.result.connect(self._extract_done)
        worker.signals.error.connect(lambda text: message(self, self.tr.text("common.error"), text, True))
        worker.signals.finished.connect(self._archive_finished)
        start_worker(self, worker)

    def _extract_done(self, results: list[tuple[Path, Path, int, int]]) -> None:
        success = sum(item[2] for item in results)
        failed = sum(item[3] for item in results)
        self.status.setText(self.tr.text("archive.done", success=success, failed=failed))

    def _pack(self) -> None:
        source = Path(self.pack_source.text())
        output = Path(self.pack_output.text())
        if not source.is_dir() or not output.name:
            return
        self.progress.show()
        self.archive_cancel.show()
        self.progress.setRange(0, 0)
        worker = Worker(self.tool.pack, source, output, self.level.value(), on_progress=self._progress)
        worker.signals.result.connect(
            lambda count: self.status.setText(f"{count} files packed")
        )
        worker.signals.error.connect(lambda text: message(self, self.tr.text("common.error"), text, True))
        worker.signals.finished.connect(self._archive_finished)
        start_worker(self, worker)

    def _progress(self, value: object) -> None:
        if isinstance(value, tuple) and len(value) == 3:
            name, current, total = value
            self.progress.setRange(0, max(1, total))
            self.progress.setValue(current)
            self.status.setText(self.tr.text("archive.running", name=name))

    def _archive_finished(self) -> None:
        self.progress.hide()
        self.archive_cancel.hide()


class PcGameDialog(QDialog):
    def __init__(self, tr: Translator, parent=None):
        super().__init__(parent)
        self.tr = tr
        self.setWindowTitle(tr.text("add.pc_title"))
        self.resize(580, 260)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.folder = QLineEdit()
        browse_folder = QPushButton(tr.text("common.browse"))
        browse_folder.clicked.connect(self._browse_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse_folder)
        form.addRow(tr.text("add.pc_folder"), folder_row)
        self.executable = QLineEdit()
        browse_exe = QPushButton(tr.text("common.browse"))
        browse_exe.clicked.connect(self._browse_executable)
        exe_row = QHBoxLayout()
        exe_row.addWidget(self.executable, 1)
        exe_row.addWidget(browse_exe)
        form.addRow(tr.text("add.pc_exe"), exe_row)
        layout.addLayout(form)
        layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr.text("add.pc_folder"), str(Path.home()))
        if path:
            self.folder.setText(path)

    def _browse_executable(self) -> None:
        start = self.folder.text() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, self.tr.text("add.pc_exe"), start)
        if path:
            self.executable.setText(os.path.relpath(path, start) if self.folder.text() else path)


class CoverSourcesDialog(QDialog):
    def __init__(self, settings: Settings, tr: Translator, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.tr = tr
        self.secrets = SecretStore()
        self.auth = HikarinagiAuth(settings, self.secrets)
        self.setWindowTitle(tr.text("settings.cover_sources"))
        self.resize(560, 480)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        enabled = settings.get("cover_enabled", {})
        order = [key for key in settings.get("cover_order", DEFAULT_COVER_ORDER) if key in COVER_SOURCES]
        for key in COVER_SOURCES:
            if key not in order:
                order.append(key)
        for key in order:
            item = QListWidgetItem(COVER_SOURCES[key])
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if enabled.get(key, True) else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list, 1)
        controls = QHBoxLayout()
        up = QPushButton("↑")
        down = QPushButton("↓")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        controls.addWidget(up)
        controls.addWidget(down)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.only_missing = QCheckBox(tr.text("settings.only_missing"))
        self.only_missing.setChecked(bool(settings.get("cover_only_missing", True)))
        layout.addWidget(self.only_missing)
        api_frame = QFrame()
        api_frame.setObjectName("Card")
        api_layout = QFormLayout(api_frame)
        api_layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel("Hikarinagi")
        title.setStyleSheet("font-weight: 700;")
        api_layout.addRow(title)
        self.hikarinagi_client = QLineEdit(str(settings.get("hikarinagi_client_id", "")))
        self.hikarinagi_token = QLineEdit(self.secrets.get("hikarinagi_access_token", ""))
        self.hikarinagi_token.setEchoMode(QLineEdit.EchoMode.Password)
        api_layout.addRow("OAuth Client ID", self.hikarinagi_client)
        api_layout.addRow("Access token", self.hikarinagi_token)
        auth_row = QHBoxLayout()
        authorize = QPushButton("Authorize in browser")
        authorize.clicked.connect(self._authorize_hikarinagi)
        clear_auth = QPushButton("Sign out")
        clear_auth.clicked.connect(self._clear_hikarinagi)
        auth_row.addWidget(authorize)
        auth_row.addWidget(clear_auth)
        auth_row.addStretch(1)
        api_layout.addRow("", auth_row)
        note = QLabel(
            "Hikarinagi uses OAuth. Paste an access token from the desktop authorization flow; "
            "the token is encrypted in the local secret store."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        api_layout.addRow(note)
        layout.addWidget(api_frame)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)

    def _save(self) -> None:
        order = []
        enabled = {}
        for index in range(self.list.count()):
            item = self.list.item(index)
            key = item.data(Qt.ItemDataRole.UserRole)
            order.append(key)
            enabled[key] = item.checkState() == Qt.CheckState.Checked
        self.settings.update(
            {
                "cover_order": order,
                "cover_enabled": enabled,
                "cover_only_missing": self.only_missing.isChecked(),
                "hikarinagi_client_id": self.hikarinagi_client.text().strip(),
            }
        )
        self.secrets.set("hikarinagi_access_token", self.hikarinagi_token.text().strip())
        self.accept()

    def _authorize_hikarinagi(self) -> None:
        self.settings.set("hikarinagi_client_id", self.hikarinagi_client.text().strip())
        worker = Worker(self.auth.authorize_interactive)

        def authorized(token: str) -> None:
            self.hikarinagi_token.setText(token)
            message(self, "Hikarinagi", "Authorization succeeded.")

        worker.signals.result.connect(authorized)
        worker.signals.error.connect(
            lambda text: message(self, self.tr.text("common.error"), text, True)
        )
        start_worker(self, worker)

    def _clear_hikarinagi(self) -> None:
        self.auth.clear()
        self.hikarinagi_token.clear()


class GameSettingsDialog(QDialog):
    def __init__(
        self,
        game: Game,
        launch_file: str | None,
        runtime_id: str | None,
        custom_args: list[str],
        save_dir: str | None,
        runtimes: RuntimeManager,
        tr: Translator,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(tr.text("game_settings.title"))
        self.resize(650, 430)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.launch_file = QLineEdit(launch_file or "")
        launch_row = QHBoxLayout()
        launch_row.addWidget(self.launch_file, 1)
        browse = QPushButton(tr.text("common.browse"))
        browse.clicked.connect(self._browse_launch)
        launch_row.addWidget(browse)
        form.addRow(tr.text("game_settings.launch_file"), launch_row)
        self.runtime = QComboBox()
        self.runtime.addItem("Auto", "")
        for key, status in runtimes.statuses().items():
            self.runtime.addItem(f"{status.name} ({tr.text('engines.ready' if status.available else 'engines.missing')})", key)
        index = self.runtime.findData(runtime_id or "")
        self.runtime.setCurrentIndex(max(0, index))
        form.addRow(tr.text("game_settings.runtime"), self.runtime)
        self.args = QLineEdit(" ".join(custom_args))
        form.addRow(tr.text("game_settings.args"), self.args)
        self.env = QTextEdit()
        self.env.setMaximumHeight(90)
        self.env.setPlaceholderText("KEY=VALUE")
        self.env.setPlainText(str(game.overrides.get("env", "")))
        form.addRow("Environment", self.env)
        self.save_dir = QLineEdit(save_dir or "")
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_dir, 1)
        browse_save = QPushButton(tr.text("common.browse"))
        browse_save.clicked.connect(self._browse_save)
        save_row.addWidget(browse_save)
        form.addRow(tr.text("game_settings.save_dir"), save_row)
        layout.addLayout(form)
        layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_launch(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr.text("game_settings.launch_file"))
        if path:
            self.launch_file.setText(path)

    def _browse_save(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr.text("game_settings.save_dir"), str(Path.home()))
        if path:
            self.save_dir.setText(path)


class PatchDialog(QDialog):
    def __init__(self, game: Game, tr: Translator, parent=None):
        super().__init__(parent)
        self.game = game
        self.tr = tr
        self.pool = QThreadPool.globalInstance()
        self.entries: list[PatchEntry] = []
        self.setWindowTitle(tr.text("games.patch"))
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.search = QLineEdit(game.title)
        self.search.setPlaceholderText(tr.text("cover.keyword"))
        refresh = QPushButton(tr.text("common.refresh"))
        refresh.clicked.connect(self._load)
        controls.addWidget(self.search, 1)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.status = QLabel(tr.text("common.working"))
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._install())
        layout.addWidget(self.list, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        install = QPushButton(tr.text("common.apply"))
        install.setObjectName("Primary")
        install.clicked.connect(self._install)
        close = QPushButton(tr.text("common.close"))
        close.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(close)
        buttons.addWidget(install)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self._filter)
        self._load()

    def _load(self) -> None:
        self.status.setText(self.tr.text("common.working"))
        worker = Worker(fetch_index)

        def done(entries: list[PatchEntry]) -> None:
            self.entries = entries
            self._filter()

        worker.signals.result.connect(done)
        worker.signals.error.connect(
            lambda text: self.status.setText(text)
        )
        start_worker(self, worker)

    def _filter(self) -> None:
        values = search_patches(self.entries, self.search.text())[:80]
        self.list.clear()
        for entry in values:
            stamp = time.strftime("%Y-%m-%d", time.localtime(entry.timestamp / 1000))
            item = QListWidgetItem(f"{entry.name}   ·   {entry.brand}   ·   {stamp}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
        self.status.setText(f"{len(values)} patches")

    def _install(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        entry: PatchEntry = item.data(Qt.ItemDataRole.UserRole)
        self.progress.show()
        worker = Worker(install_patch, self.game, entry.patches, on_progress=self.status.setText)
        worker.signals.progress.connect(self.status.setText)
        worker.signals.result.connect(
            lambda names: message(self, self.tr.text("common.done"), "\n".join(names))
        )
        worker.signals.error.connect(
            lambda text: message(self, self.tr.text("common.error"), text, True)
        )
        worker.signals.finished.connect(self.progress.hide)
        start_worker(self, worker)


class UpdateDialog(QDialog):
    def __init__(self, tr: Translator, parent=None):
        super().__init__(parent)
        self.tr = tr
        self.pool = QThreadPool.globalInstance()
        self.setWindowTitle("Check for updates")
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        self.status = QLabel(tr.text("common.working"))
        self.status.setObjectName("Muted")
        layout.addWidget(self.status)
        self.notes = QTextBrowser()
        self.notes.setReadOnly(True)
        layout.addWidget(self.notes, 1)
        close = QPushButton(tr.text("common.close"))
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        worker = Worker(check_updates, True)
        worker.signals.result.connect(self._show)
        worker.signals.error.connect(lambda text: self.status.setText(text))
        start_worker(self, worker)

    def _show(self, result) -> None:
        import webbrowser

        current, releases = result
        self.status.setText(f"Current version: {current}")
        if not releases:
            self.notes.setPlainText("No releases are available.")
            return
        latest = releases[0]
        self.notes.setMarkdown(
            f"## {latest.name}\n\n"
            f"Tag: `{latest.tag}` · {latest.published_at}\n\n"
            f"{latest.body}\n\n"
            f"[Open release page]({latest.page_url})"
        )
        self.notes.anchorClicked.connect(lambda url: webbrowser.open(url.toString()))


def _parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip():
            result[key.strip()] = value.strip()
    return result
