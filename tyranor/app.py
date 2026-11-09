from __future__ import annotations

import argparse
import base64
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QByteArray, QEvent, QPoint, QSize, Qt, QThreadPool, QTimer
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, __version__
from .covers import CoverError, CoverService
from .database import Library
from .i18n import Translator, resolve_language
from .launcher import LaunchStatus, Launcher, split_args
from .models import EngineType, Game
from .paths import asset_path, log_path
from .patches import PatchError
from .qtwebengine import prepare_qtwebengine
from .runtimes import RuntimeManager
from .saves import SaveError, SaveManager
from .scanner import ScanResult, Scanner, merge_scan_results
from .settings import DEFAULTS, Settings
from .shortcuts import create_shortcut
from .webdav import WebDavSync
from .ui.dialogs import (
    CoverDialog,
    CoverSourcesDialog,
    GameDetailsDialog,
    GameSettingsDialog,
    OnboardingDialog,
    PatchDialog,
    PcGameDialog,
    RuntimeDialog,
    SaveManagerDialog,
    WebDavDialog,
    confirm,
    message,
)
from .ui.pages import EnginesPage, HomePage, LibraryPage, SettingsPage
from .ui.theme import GradientRoot, apply_theme
from .ui.widgets import NavButton
from .ui.workers import Worker


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings()
        self.tr = Translator(resolve_language(self.settings.get("language", "zh_CN")))
        self.library = Library()
        self.runtimes = RuntimeManager(self.settings)
        self.runtimes.refresh()
        self.covers = CoverService(self.settings)
        self.launcher = Launcher(self.library, self.runtimes, on_exited=self._game_exited)
        self.saves = SaveManager(self.library, self.is_game_running)
        self.webdav = WebDavSync(self.settings, self.saves)
        legacy_webdav_password = self.settings.get("save_sync_password", "")
        if legacy_webdav_password:
            self.webdav.secrets.set("webdav_password", str(legacy_webdav_password))
            self.settings.pop("save_sync_password")
        self.pool = QThreadPool.globalInstance()
        self._workers: list[Worker] = []
        self._scan_worker: Worker | None = None
        self._building = False
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        icon = QIcon(str(asset_path("icon.png")))
        self.setWindowIcon(icon)
        self.setAcceptDrops(True)
        self.resize(1280, 820)
        self.setMinimumSize(980, 640)
        self._setup_ui()
        self._restore_geometry()
        self.refresh_all()
        if not self.settings.get("onboarding_done", False) and not os.environ.get("TYRANOR_SKIP_ONBOARDING"):
            if self.library.count() > 0 or self.library.roots():
                self.settings.set("onboarding_done", True)
            else:
                QTimer.singleShot(220, self._show_onboarding)

    def _setup_ui(self) -> None:
        self.root = GradientRoot(self.settings)
        self.setCentralWidget(self.root)
        shell = QHBoxLayout(self.root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(218)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(18, 22, 18, 20)
        side.setSpacing(9)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setFixedSize(42, 42)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = QPixmap(str(asset_path("icon.png"))).scaled(
            42,
            42,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        mark.setPixmap(logo)
        mark.setStyleSheet("border-radius: 13px;")
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel("Tyranor NEXT")
        name.setStyleSheet("font-size: 17px; font-weight: 800;")
        subtitle = QLabel("LINUX · NATIVE")
        subtitle.setObjectName("Muted")
        subtitle.setStyleSheet("font-size: 9px; letter-spacing: 1.4px;")
        brand_text.addWidget(name)
        brand_text.addWidget(subtitle)
        brand.addWidget(mark)
        brand.addSpacing(4)
        brand.addLayout(brand_text)
        brand.addStretch(1)
        side.addLayout(brand)
        side.addSpacing(22)
        self.nav_buttons: list[NavButton] = []
        for index, (icon, label) in enumerate(
            (
                ("⌂", "nav.home"),
                ("▣", "nav.games"),
                ("◇", "nav.engines"),
                ("⚙", "nav.settings"),
            )
        ):
            button = NavButton(icon, self.tr.text(label))
            button.clicked.connect(lambda checked=False, page=index: self.navigate(page))
            side.addWidget(button)
            self.nav_buttons.append(button)
        side.addStretch(1)
        self.side_status = QLabel()
        self.side_status.setObjectName("Muted")
        self.side_status.setWordWrap(True)
        self.side_status.setStyleSheet("font-size: 11px; padding: 8px;")
        side.addWidget(self.side_status)
        version = QLabel(f"v{__version__} · GPL-2.0")
        version.setObjectName("Muted")
        version.setStyleSheet("font-size: 10px;")
        side.addWidget(version)
        shell.addWidget(self.sidebar)
        self.pages = QStackedWidget()
        shell.addWidget(self.pages, 1)
        self._create_pages()
        self.toast = QLabel(self.root)
        self.toast.setWordWrap(True)
        self.toast.setMaximumWidth(460)
        self.toast.setStyleSheet(
            "background: rgba(24, 34, 48, 0.94); color: white; border-radius: 11px; "
            "padding: 10px 15px; font-weight: 600;"
        )
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)
        self.navigate(int(self.settings.get("last_page", 0)) if str(self.settings.get("last_page", "0")).isdigit() else 0)

    def _create_pages(self) -> None:
        while self.pages.count():
            widget = self.pages.widget(0)
            self.pages.removeWidget(widget)
            widget.deleteLater()
        self.home_page = HomePage(self, self.tr, self.settings)
        self.library_page = LibraryPage(self, self.tr, self.settings)
        self.engines_page = EnginesPage(self, self.tr, self.settings, self.runtimes)
        self.settings_page = SettingsPage(self, self.tr, self.settings)
        for page in (self.home_page, self.library_page, self.engines_page, self.settings_page):
            self.pages.addWidget(page)
        self._connect_signals()

    def _connect_signals(self) -> None:
        home = self.home_page
        home.open_library.connect(lambda: self.navigate(1))
        home.open_game.connect(self.show_game)
        home.launch_game.connect(self.launch_game)
        library = self.library_page
        library.add_folder.connect(self.add_scan_root)
        library.add_pc.connect(self.add_pc_game)
        library.scan.connect(self.scan_library)
        library.open_game.connect(self.show_game)
        library.launch_game.connect(self.launch_game)
        library.change_cover.connect(self.change_cover)
        library.save_manager.connect(self.open_save_manager)
        library.game_settings.connect(self.open_game_settings)
        library.delete_game.connect(self.delete_game)
        library.toggle_quick.connect(self.toggle_quick)
        library.open_folder.connect(self.open_game_folder)
        engines = self.engines_page
        engines.configure_runtime.connect(self.configure_runtime)
        engines.archive_tool.connect(self.open_archive_tool)
        settings = self.settings_page
        settings.add_root.connect(self.add_scan_root)
        settings.remove_root.connect(self.remove_scan_root)
        settings.scrape_covers.connect(self.scrape_covers)
        settings.cover_sources.connect(self.open_cover_sources)
        settings.webdav.connect(self.open_webdav)
        settings.logs.connect(self.open_logs)
        settings.reset.connect(self.reset_settings)
        settings.clean_missing.connect(self.clean_missing_games)
        settings.language_changed.connect(self.rebuild_for_language)
        settings.theme_changed.connect(self.apply_theme)

    def navigate(self, index: int) -> None:
        index = max(0, min(index, self.pages.count() - 1))
        self.pages.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)
        self.settings.set("last_page", str(index))

    def refresh_all(self) -> None:
        games = self.library.all_games()
        recent = self.library.recent_games(int(self.settings.get("recent_limit", 20)))
        quick = self.library.quick_games()
        self.home_page.refresh(games, recent, quick)
        self.library_page.refresh_games(games)
        self.engines_page.refresh_engines(games)
        self.settings_page._build()
        visible = len(self.runtimes.visible_engines())
        self.side_status.setText(
            f"{len(games)} {self.tr.text('engines.games')}\n"
            f"{visible} {self.tr.text('engines.runtime')}\n"
            f"{len(self.library.roots())} scan roots"
        )

    def data_changed(self) -> None:
        if self._building:
            return
        self._building = True
        QTimer.singleShot(0, self._finish_data_change)

    def _finish_data_change(self) -> None:
        self._building = False
        games = self.library.all_games()
        recent = self.library.recent_games(int(self.settings.get("recent_limit", 20)))
        quick = self.library.quick_games()
        self.home_page.refresh(games, recent, quick)
        self.library_page.refresh_games(games)
        self.engines_page.refresh_engines(games)
        visible = len(self.runtimes.visible_engines())
        self.side_status.setText(
            f"{len(games)} {self.tr.text('engines.games')}\n"
            f"{visible} {self.tr.text('engines.runtime')}\n"
            f"{len(self.library.roots())} scan roots"
        )

    def apply_theme(self) -> None:
        app = QApplication.instance()
        if app:
            apply_theme(app, self.settings)
        self.root.update()
        self.centralWidget().update()

    def rebuild_for_language(self) -> None:
        self.tr.set_language(resolve_language(self.settings.get("language", "zh_CN")))
        for button, (icon, key) in zip(
            self.nav_buttons,
            (
                ("⌂", "nav.home"),
                ("▣", "nav.games"),
                ("◇", "nav.engines"),
                ("⚙", "nav.settings"),
            ),
        ):
            button.setText(f"  {icon}   {self.tr.text(key)}")
        current = self.pages.currentIndex()
        self._create_pages()
        self.navigate(current)
        self.refresh_all()

    def add_scan_root(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, self.tr.text("add.folder_title"), str(Path.home())
        )
        if not path:
            return
        self.library.add_root(path)
        self.settings_page._build()
        self.scan_library()

    def remove_scan_root(self, path: str) -> None:
        if confirm(self, self.tr.text("common.confirm"), f"{self.tr.text('common.remove')}\n{path}"):
            self.library.remove_root(path)
            self.settings_page._build()
            self.data_changed()

    def scan_library(self) -> None:
        roots = self.library.roots()
        if not roots:
            self.add_scan_root()
            return
        if self._scan_worker is not None:
            self.show_toast(self.tr.text("common.working"))
            return
        self.show_toast(self.tr.text("toast.scan_started"))
        progress_worker: Worker

        def scan_job() -> ScanResult:
            scanner = Scanner(
                self.library,
                on_progress=progress_worker.signals.progress.emit,
            )
            return scanner.scan(roots, int(self.settings.get("scan_depth", 3)))

        worker = Worker(scan_job)
        progress_worker = worker
        self._scan_worker = worker
        self._track_worker(worker)
        worker.signals.progress.connect(self._scan_progress)
        worker.signals.result.connect(self._scan_done)
        worker.signals.error.connect(
            lambda text: message(self, self.tr.text("common.error"), text, True)
        )
        worker.signals.finished.connect(self._scan_finished)
        self.pool.start(worker)

    def _scan_progress(self, text: str) -> None:
        self.side_status.setText(text)

    def _scan_done(self, result: ScanResult) -> None:
        existing = self.library.all_games()
        merged = merge_scan_results(existing, result.games)
        scanned_uris = {game.uri for game in merged}
        for game in existing:
            game.missing = (
                game.engine is not EngineType.PC
                and game.uri not in scanned_uris
                and not Path(game.uri).exists()
            )
        self.library.upsert_games(merged + [game for game in existing if game.uri not in scanned_uris])
        self.refresh_all()
        self.show_toast(self.tr.text("toast.scan_done", count=len(result.games)))

    def _scan_finished(self) -> None:
        self._scan_worker = None

    def add_pc_game(self) -> None:
        dialog = PcGameDialog(self.tr, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        folder = Path(dialog.folder.text()).expanduser()
        executable = dialog.executable.text().strip()
        if not folder.is_dir() or not executable:
            message(self, self.tr.text("common.error"), self.tr.text("add.pc_exe"), True)
            return
        game = Game(
            uri=str(folder.resolve()),
            title=folder.name,
            engine=EngineType.PC,
            launch_target=executable,
            launch_file=executable,
            runtime_id="wine",
        )
        self.library.save_game(game)
        self.refresh_all()
        self.show_toast(game.title)

    def launch_game(self, game: Game) -> None:
        result = self.launcher.launch(game)
        if not result.ok:
            title = (
                self.tr.text("toast.launch_failed")
                if result.status is not LaunchStatus.ALREADY_RUNNING
                else self.tr.text("common.warning")
            )
            message(self, title, result.message, result.status is not LaunchStatus.ALREADY_RUNNING)
            return
        self.show_toast(f"{self.tr.text('games.launch')} · {game.title}")
        self.data_changed()
        if self.settings.get("minimize_on_launch", False):
            self.showMinimized()
        if self.settings.get("close_after_launch", False):
            self.close()

    def show_game(self, game: Game) -> None:
        dialog = GameDetailsDialog(game, self.launcher, self.tr, self)
        dialog.action_requested.connect(
            lambda action: self._game_action(game, action, dialog)
        )
        dialog.exec()
        self.data_changed()

    def _game_action(self, game: Game, action: str, dialog: GameDetailsDialog) -> None:
        if action == "launch_file":
            self.choose_launch_file(game)
        elif action == "shortcut":
            try:
                path = create_shortcut(game)
                self.show_toast(str(path))
            except OSError as exc:
                message(self, self.tr.text("common.error"), str(exc), True)
        elif action == "game_log":
            path = self.launcher.log_path(game)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            subprocess.Popen(["xdg-open", str(path)])
        elif action == "cover":
            self.change_cover(game)
        elif action == "saves":
            self.open_save_manager(game)
        elif action == "patch":
            PatchDialog(game, self.tr, self).exec()
        elif action == "settings":
            self.open_game_settings(game)
        elif action == "rename":
            text, ok = QInputDialog.getText(
                self, self.tr.text("games.rename"), self.tr.text("games.rename"), text=game.title
            )
            if ok and text.strip():
                game.title = text.strip()
                self.library.save_game(game)
                self.data_changed()
        elif action == "folder":
            self.open_game_folder(game)
        elif action == "delete":
            self.delete_game(game)
        dialog.accept()

    def choose_launch_file(self, game: Game) -> None:
        root = Path(game.uri)
        if not root.is_dir():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr.text("games.launch_file"), str(root)
        )
        if path:
            candidate = Path(path).resolve()
            try:
                game.launch_file = str(candidate.relative_to(root.resolve()))
            except ValueError:
                game.launch_file = candidate.name
            self.library.save_game(game)
            self.data_changed()

    def change_cover(self, game: Game) -> None:
        dialog = CoverDialog(game, self.covers, self.tr, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.library.save_game(game)
            self.data_changed()

    def open_save_manager(self, game: Game) -> None:
        SaveManagerDialog(game, self.saves, self.tr, self, self.webdav).exec()

    def open_game_settings(self, game: Game) -> None:
        dialog = GameSettingsDialog(
            game,
            game.launch_file,
            game.runtime_id,
            game.custom_args,
            game.save_dir,
            self.runtimes,
            self.tr,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        game.launch_file = dialog.launch_file.text().strip() or None
        game.runtime_id = dialog.runtime.currentData() or None
        game.custom_args = split_args(dialog.args.text())
        env_text = dialog.env.toPlainText().strip()
        if env_text:
            game.overrides["env"] = env_text
        else:
            game.overrides.pop("env", None)
        game.save_dir = dialog.save_dir.text().strip() or None
        self.library.save_game(game)
        self.data_changed()

    def delete_game(self, game: Game) -> None:
        if not confirm(
            self,
            self.tr.text("common.confirm"),
            self.tr.text("toast.delete_confirm", title=game.title),
        ):
            return
        self.library.delete_game(game.uri)
        self.data_changed()

    def toggle_quick(self, game: Game) -> None:
        if not self.library.set_quick(game.uri, not game.quick_launch):
            self.show_toast(self.tr.text("toast.quick_limit"))
        self.data_changed()

    def open_game_folder(self, game: Game) -> None:
        path = Path(game.uri)
        folder = path if path.is_dir() else path.parent
        subprocess.Popen(["xdg-open", str(folder)])

    def configure_runtime(self, key: str) -> None:
        if RuntimeDialog(self.runtimes, key, self.tr, self).exec() == QDialog.DialogCode.Accepted:
            self.runtimes.refresh()
            self.refresh_all()
            self.show_toast(self.tr.text("runtime.saved"))

    def open_archive_tool(self) -> None:
        from .ui.dialogs import ArchiveDialog

        ArchiveDialog(self.tr, self).exec()

    def scrape_covers(self) -> None:
        games = self.library.all_games()
        worker = Worker(
            self.covers.batch_scrape,
            games,
        )
        self._track_worker(worker)
        worker.signals.result.connect(lambda result: self._covers_done(result, games))
        worker.signals.error.connect(
            lambda text: message(self, self.tr.text("common.error"), text, True)
        )
        self.pool.start(worker)
        self.show_toast(self.tr.text("common.working"))

    def _covers_done(self, result: tuple[int, int, int], games: list[Game]) -> None:
        updated, skipped, failed = result
        self.library.upsert_games(games)
        self.refresh_all()
        self.show_toast(
            self.tr.text(
                "cover.batch_done",
                updated=updated,
                skipped=skipped,
                failed=failed,
            )
        )

    def open_cover_sources(self) -> None:
        if CoverSourcesDialog(self.settings, self.tr, self).exec() == QDialog.DialogCode.Accepted:
            self.data_changed()

    def open_webdav(self) -> None:
        if WebDavDialog(self.settings, self.webdav, self.library.all_games(), self.tr, self).exec():
            self.data_changed()

    def open_logs(self) -> None:
        log_path().touch(exist_ok=True)
        subprocess.Popen(["xdg-open", str(log_path())])

    def reset_settings(self) -> None:
        if not confirm(self, self.tr.text("common.confirm"), self.tr.text("settings.reset")):
            return
        current_roots = self.library.roots()
        self.settings.update(DEFAULTS)
        self.webdav.secrets.delete("webdav_password")
        for root in current_roots:
            self.library.add_root(root)
        self.tr.set_language(resolve_language(self.settings.get("language", "zh_CN")))
        app = QApplication.instance()
        if app:
            apply_theme(app, self.settings)
        self._create_pages()
        self.navigate(0)
        self.refresh_all()

    def clean_missing_games(self) -> None:
        candidates = [
            game
            for game in self.library.all_games()
            if game.missing or not (Path(game.uri).exists())
        ]
        if not candidates:
            self.show_toast(self.tr.text("common.done"))
            return
        if not confirm(
            self,
            self.tr.text("settings.clean_missing"),
            f"{len(candidates)} records",
        ):
            return
        for game in candidates:
            self.library.delete_game(game.uri)
        self.refresh_all()

    def is_game_running(self, uri: str) -> bool:
        running = self.launcher.running.get(uri)
        return bool(running and running.process.poll() is None)

    def _game_exited(self, game: Game, running, code: int) -> None:
        QTimer.singleShot(0, self.data_changed)

    def _track_worker(self, worker: Worker) -> None:
        self._workers.append(worker)
        worker.signals.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)

    def _show_onboarding(self) -> None:
        dialog = OnboardingDialog(self.tr, self.settings, self)
        dialog.page_requested.connect(self.navigate)
        dialog.exec()

    def show_toast(self, text: str) -> None:
        self.toast.setText(text)
        self.toast.adjustSize()
        x = self.root.width() - self.toast.width() - 26
        y = self.root.height() - self.toast.height() - 24
        self.toast.move(max(20, x), max(20, y))
        self.toast.raise_()
        self.toast.show()
        self._toast_timer.start(2800)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.move(
                max(20, self.root.width() - self.toast.width() - 26),
                max(20, self.root.height() - self.toast.height() - 24),
            )

    def dragEnterEvent(self, event) -> None:
        if any(
            url.isLocalFile() and Path(url.toLocalFile()).is_dir()
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        added = False
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_dir():
                self.library.add_root(str(path))
                added = True
        if added:
            self.refresh_all()
            self.scan_library()
            event.acceptProposedAction()

    def _restore_geometry(self) -> None:
        geometry = self.settings.get("window_geometry", "")
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
                return
            except Exception:
                pass
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.resize(min(1320, int(available.width() * 0.86)), min(880, int(available.height() * 0.86)))
            frame = self.frameGeometry()
            frame.moveCenter(available.center())
            self.move(frame.topLeft())

    def closeEvent(self, event) -> None:
        self.settings.set(
            "window_geometry",
            bytes(self.saveGeometry().toBase64()).decode("ascii"),
        )
        self.launcher.detach_tracking()
        super().closeEvent(event)


def _configure_logging() -> None:
    logging.basicConfig(
        filename=log_path(),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tyranor-next", description=APP_NAME)
    parser.add_argument("--scan", metavar="PATH", help="add a scan root and open the game library")
    parser.add_argument("--launch-uri", metavar="URI", help="launch one game by its library URI")
    parser.add_argument("--no-onboarding", action="store_true")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.no_onboarding:
        os.environ["TYRANOR_SKIP_ONBOARDING"] = "1"
    _configure_logging()
    prepare_qtwebengine()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Tyranor Next")
    app.setDesktopFileName("io.github.tyranornext.linux")
    settings = Settings()
    apply_theme(app, settings)
    window = MainWindow(settings)
    window.show()
    if args.scan:
        window.library.add_root(args.scan)
        window.refresh_all()
        QTimer.singleShot(250, window.scan_library)
        QTimer.singleShot(260, lambda: window.navigate(1))
    if args.launch_uri:
        game = window.library.get_game(args.launch_uri)
        if game is None:
            message(window, APP_NAME, f"Game not found: {args.launch_uri}", True)
        else:
            QTimer.singleShot(180, lambda: window.launch_game(game))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
