from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import mimetypes
import os
import re
import signal
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

from .asar import AsarArchive, AsarError
from .qtwebengine import (
    QWEBENGINE_AVAILABLE,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineView,
    prepare_qtwebengine,
)

_STORAGE_PREFIX = "/__tyranor/storage/"
_MAX_STORAGE_BYTES = 128 * 1024 * 1024
_TYRANO_STORAGE_SHIM = rb"""

// Tyranor Next browser storage bridge. Tyrano's Electron build uses Node's
// synchronous file APIs; the embedded Linux host persists the same values
// through this local HTTP endpoint instead.
(function () {
    if (typeof window.global === "undefined") {
        window.global = window;
    }
    if (typeof $ === "undefined" || typeof XMLHttpRequest === "undefined") {
        return;
    }

    function storageRequest(method, key, body) {
        var xhr = new XMLHttpRequest();
        xhr.open(method, "/__tyranor/storage/" + encodeURIComponent(key), false);
        xhr.setRequestHeader("Content-Type", "text/plain;charset=UTF-8");
        xhr.send(body === undefined ? null : body);
        if (xhr.status === 404) {
            return null;
        }
        if (xhr.status < 200 || xhr.status >= 300) {
            throw new Error("Tyranor storage request failed: HTTP " + xhr.status);
        }
        return xhr.responseText;
    }

    $.setStorageFile = function (key, value) {
        storageRequest("PUT", key, escape(JSON.stringify(value)));
    };
    $.getStorageFile = function (key) {
        var value = storageRequest("GET", key);
        return value === null ? null : unescape(value);
    };

    // Tyrano can rebuild its click layer after the first scenario has loaded.
    // In a browser this replaces the element that owns the click handler, so
    // later pages stop responding. Preserve the original handler and attach it
    // to every replacement layer.
    var clickCompat = {handler: null};
    function fallbackClickHandler() {
        var kag = window.TYRANO && TYRANO.kag;
        if (!kag) {
            return;
        }
        if (kag.tmp.ready_audio == 0 && $.isNeedClickAudio()) {
            kag.readyAudio();
            kag.tmp.ready_audio = true;
            if (kag.stat.is_adding_text == 1) {
                kag.stat.is_click_text = true;
                return;
            }
            kag.ftag.nextOrder();
            return;
        }
        if (kag.key_mouse.is_swipe) {
            kag.key_mouse.is_swipe = false;
            return;
        }
        if (kag.stat.is_hide_message == 1) {
            kag.layer.showMessageLayers();
            return;
        }
        if (kag.stat.is_adding_text == 1) {
            kag.stat.is_click_text = true;
            return;
        }
        if (kag.stat.is_click_text == 1 || kag.stat.is_stop == 1) {
            return;
        }
        if (kag.stat.fuki.active == 1) {
            kag.layer.hideMessageLayers();
        }
        kag.ftag.nextOrder();
    }

    function parseEventData(element) {
        try {
            return JSON.parse(element.getAttribute("data-event-pm") || "{}");
        } catch (error) {
            return {};
        }
    }

    function activateEventElement(element) {
        var kag = window.TYRANO && window.TYRANO.kag;
        var pm = parseEventData(element);
        var tag = element.getAttribute("data-event-tag") || "";
        if (!kag) {
            return;
        }
        if (tag === "button" && pm.role) {
            kag.stat.is_skip = false;
            if (pm.role !== "auto") {
                kag.ftag.startTag("autostop", {next: "false"});
            }
            switch (pm.role) {
                case "save":
                    kag.menu.displaySave();
                    break;
                case "load":
                    kag.menu.displayLoad();
                    break;
                case "window":
                    kag.layer.hideMessageLayers();
                    break;
                case "title":
                    kag.backTitle();
                    break;
                case "menu":
                    kag.menu.showMenu();
                    break;
                case "skip":
                    kag.ftag.startTag("skipstart", {});
                    break;
                case "backlog":
                    kag.menu.displayLog();
                    break;
                case "fullscreen":
                    kag.menu.screenFull();
                    break;
                case "quicksave":
                    kag.menu.setQuickSave();
                    break;
                case "quickload":
                    kag.menu.loadQuickSave();
                    break;
                case "auto":
                    kag.stat.is_auto == 1
                        ? kag.ftag.startTag("autostop", {next: "false"})
                        : kag.ftag.startTag("autostart", {});
                    break;
                case "sleepgame":
                    kag.tmp.sleep_game = {};
                    pm.next = false;
                    kag.ftag.startTag("sleepgame", pm);
                    break;
            }
            return;
        }
        if (tag === "link") {
            kag.ftag.nextOrderWithLabel(pm.target, pm.storage);
            return;
        }
        if (tag === "clickable" || tag === "glink" || tag === "button") {
            kag.layer.showEventLayer();
            if (pm.cm === "true") {
                kag.ftag.startTag("cm", {});
            }
            kag.ftag.startTag("jump", pm);
        }
    }

    function hideMenu(empty) {
        var kag = window.TYRANO && window.TYRANO.kag;
        if (!kag) {
            return;
        }
        var menu = kag.layer.getMenuLayer();
        menu.stop(true, true).fadeOut(120, function () {
            if (empty) {
                menu.empty();
            }
        });
        if (kag.stat.visible_menu_button == 1) {
            $(".button_menu").show();
        }
    }

    function activateMenuElement(element) {
        var kag = window.TYRANO && window.TYRANO.kag;
        if (!kag) {
            return;
        }
        if (element.matches(".save_display_area")) {
            var num = Number(element.getAttribute("data-num"));
            var menu = kag.layer.getMenuLayer();
            kag.menu.snap = null;
            if ($(".img_label_save").length) {
                menu.hide().empty();
                if (kag.stat.visible_menu_button == 1) {
                    $(".button_menu").show();
                }
                kag.menu.doSave(num);
            } else if ($(".img_label_load").length) {
                kag.menu.loadGame(num);
                menu.hide().empty();
                if (kag.stat.visible_menu_button == 1) {
                    $(".button_menu").show();
                }
            }
            return;
        }
        if (element.matches(".page_selector_button")) {
            var page = Number(element.getAttribute("data-index"));
            kag.variable.sf.last_save_page_num = page;
            $(".save_list_item").hide();
            if (typeof show_page === "function") {
                show_page(page);
            }
            return;
        }
        if (element.matches(".menu_close")) {
            hideMenu(false);
            return;
        }
        if (element.matches(".menu_window_close")) {
            kag.layer.hideMessageLayers();
            hideMenu(false);
            return;
        }
        if (element.matches(".menu_save")) {
            kag.menu.displaySave();
            return;
        }
        if (element.matches(".menu_load")) {
            kag.menu.displayLoad();
            return;
        }
        if (element.matches(".menu_skip")) {
            hideMenu(true);
            kag.stat.is_skip = true;
            if ($(".layer_event_click").css("display") !== "none") {
                kag.ftag.nextOrder();
            }
            return;
        }
        if (element.matches(".menu_back_title")) {
            kag.backTitle();
        }
    }

    var actionableSelector = [
        ".event-setting-element",
        ".save_display_area",
        ".page_selector_button",
        ".menu_close",
        ".menu_save",
        ".menu_load",
        ".menu_window_close",
        ".menu_skip",
        ".menu_back_title"
    ].join(",");

    document.addEventListener("click", function (event) {
        if (window.__tyranorNextDispatch) {
            return;
        }
        var target = event.target;
        var element = target && target.closest
            ? target.closest(actionableSelector)
            : null;
        if (!element && event.clientX != null) {
            var x = event.clientX;
            var y = event.clientY;
            var candidates = Array.from(
                document.querySelectorAll(actionableSelector)
            ).filter(function (candidate) {
                var rect = candidate.getBoundingClientRect();
                return rect.width && rect.height &&
                    x >= rect.left && x <= rect.right &&
                    y >= rect.top && y <= rect.bottom;
            });
            candidates.sort(function (left, right) {
                var a = left.getBoundingClientRect();
                var b = right.getBoundingClientRect();
                return a.width * a.height - b.width * b.height;
            });
            element = candidates[0] || null;
        }
        if (!element) {
            return;
        }
        var eventData = $._data(element, "events");
        var clickEvents = eventData && eventData.click;
        event.preventDefault();
        event.stopImmediatePropagation();
        if (clickEvents && clickEvents.length) {
            window.__tyranorNextDispatch = true;
            try {
                $(element).trigger("click");
            } finally {
                window.__tyranorNextDispatch = false;
            }
        } else {
            if (element.matches(".event-setting-element")) {
                activateEventElement(element);
            } else {
                activateMenuElement(element);
            }
        }
    }, true);

    setInterval(function () {
        var kag = window.TYRANO && window.TYRANO.kag;
        if (!kag) {
            return;
        }
        var element = document.querySelector(".layer_event_click");
        if (!element) {
            return;
        }
        var eventData = $._data(element, "events");
        var clickEvents = eventData && eventData.click;
        if (clickEvents && clickEvents.length) {
            if (!clickCompat.handler) {
                clickCompat.handler = clickEvents[0].handler;
            }
            return;
        }
        if (element.__tyranorNextClickBound) {
            return;
        }
        element.__tyranorNextClickBound = true;
        $(element).on(
            "click.tyranor-next",
            clickCompat.handler || fallbackClickHandler
        );
    }, 100);
})();
"""


class _LoggingWebPage(QWebEnginePage if QWebEnginePage is not None else object):
    def javaScriptConsoleMessage(
        self,
        level: object,
        message: str,
        line_number: int,
        source_id: str,
    ) -> None:
        level_name = getattr(level, "name", str(level))
        print(
            f"[web-console {level_name}] {source_id}:{line_number}: {message}",
            flush=True,
        )
        if QWebEnginePage is not None:
            super().javaScriptConsoleMessage(
                level,
                message,
                line_number,
                source_id,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Tyranor Next local web game host")
    parser.add_argument("--root", required=True)
    parser.add_argument("--title", default="Tyranor Next")
    parser.add_argument("--entry")
    parser.add_argument("--savedata-dir")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Game directory does not exist: {root}")
    asar_path = _find_asar(root)
    archive = AsarArchive(asar_path) if asar_path else None
    entry = _resolve_asar_entry(archive, args.entry) if archive else _resolve_entry(root, args.entry)
    storage_dir = (
        Path(args.savedata_dir).expanduser().resolve()
        if args.savedata_dir
        else root / "savedata"
    )
    storage_dir.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(
        _Handler,
        directory=str(root),
        entry=entry,
        archive=archive,
        storage_dir=storage_dir,
    )
    origin_key = str(root).encode("utf-8")
    preferred_port = 22000 + int(hashlib.sha256(origin_key).hexdigest()[:8], 16) % 10000
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", preferred_port), handler)
    except OSError as exc:
        raise SystemExit(
            f"Local web host port {preferred_port} is unavailable; "
            "close the existing game instance and retry."
        ) from exc
    port = server.server_address[1]
    if archive:
        relative = str(entry or "index.html")
    else:
        relative = entry.relative_to(root).as_posix() if entry and entry.is_relative_to(root) else "index.html"
    url = f"http://127.0.0.1:{port}/{urllib.parse.quote(relative)}"
    print(url, flush=True)
    thread = threading.Thread(target=server.serve_forever, name="web-game-host", daemon=True)
    thread.start()
    stop = threading.Event()
    qt_app = None

    def shutdown(*_: object) -> None:
        stop.set()
        server.shutdown()
        if qt_app is not None:
            qt_app.quit()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    if prepare_qtwebengine() and QWebEngineView is not None:
        from PyQt6.QtCore import QTimer, QUrl
        from PyQt6.QtWidgets import QApplication

        app = QApplication(sys.argv[:1])
        qt_app = app
        app.setApplicationName(args.title)
        view = QWebEngineView()
        view.setWindowTitle(args.title)
        view.resize(1280, 720)
        if QWebEnginePage is not None:
            if QWebEngineProfile is not None:
                profile = QWebEngineProfile("tyranor-next", app)
                browser_dir = storage_dir / "browser"
                profile.setPersistentStoragePath(str(browser_dir / "storage"))
                profile.setCachePath(str(browser_dir / "cache"))
                page = _LoggingWebPage(profile, view)
            else:
                page = _LoggingWebPage(view)
            view.setPage(page)
        view.loadStarted.connect(lambda: print(f"[web-load] started {url}", flush=True))
        view.loadFinished.connect(
            lambda ok: print(f"[web-load] finished ok={ok} url={view.url().toString()}", flush=True)
        )
        view.renderProcessTerminated.connect(
            lambda status, code: print(
                f"[web-render] terminated status={status} exit={code}",
                flush=True,
            )
        )
        view.setUrl(QUrl(url))
        view.show()
        view.raise_()
        view.activateWindow()
        view.setFocus()

        def focus_web_view() -> None:
            view.setFocus()
            proxy = view.focusProxy()
            if proxy is not None:
                proxy.setFocus()

        QTimer.singleShot(150, focus_web_view)
        test_save = os.environ.get("TYRANOR_WEB_TEST_SAVE") == "1"
        if test_save:
            test_timer = QTimer(view)
            test_timer.setInterval(700)

            def run_save_test() -> None:
                view.page().runJavaScript(
                    """
                    (function () {
                        var kag = window.TYRANO && TYRANO.kag;
                        if (!kag) {
                            return;
                        }
                        window.__tyranorSaveTest =
                            window.__tyranorSaveTest || {stage: 0};
                        var test = window.__tyranorSaveTest;
                        if (kag.stat.current_scenario === "first.ks") {
                            $('.layer_event_click').trigger('click');
                            return;
                        }
                        if (kag.stat.current_scenario === "title.ks" &&
                            test.stage === 0) {
                            var start = $('img[src$="title/start.png"]');
                            if (start.length) {
                                test.stage = 1;
                                start.trigger('click');
                            }
                            return;
                        }
                        if (kag.stat.current_scenario.indexOf("chapter1") === 0 &&
                            test.stage === 1) {
                            test.stage = 2;
                            setTimeout(function () {
                                kag.menu.displaySave();
                            }, 1000);
                            return;
                        }
                        if (test.stage === 2 &&
                            $('.save_display_area').length) {
                            test.stage = 3;
                            $('.save_display_area').eq(0).trigger('click');
                            console.log("[save-test] clicked first save slot");
                        }
                    })();
                    """,
                )

            test_timer.timeout.connect(run_save_test)
            test_timer.start()
        autoclick_delay = int(os.environ.get("TYRANOR_WEB_AUTOCLICK_MS", "0"))
        if autoclick_delay > 0:
            autoclick = QTimer(view)
            autoclick.setInterval(autoclick_delay)
            autoclick.timeout.connect(
                lambda: view.page().runJavaScript(
                    """
                    (function () {
                        var kag = window.TYRANO && TYRANO.kag;
                        if (!kag) {
                            return "no-kag";
                        }
                        var before = {
                            scenario: kag.stat.current_scenario,
                            index: kag.ftag.current_order_index,
                            isStop: kag.stat.is_stop,
                            isAddingText: kag.stat.is_adding_text,
                            isClickText: kag.stat.is_click_text
                        };
                        if (kag.stat.current_scenario === "title.ks") {
                            $('img[src$="title/start.png"]').trigger("click");
                        } else {
                            $('.layer_event_click').trigger('click');
                        }
                        return JSON.stringify({
                            before: before,
                            after: {
                                scenario: kag.stat.current_scenario,
                                index: kag.ftag.current_order_index,
                                isStop: kag.stat.is_stop,
                                isAddingText: kag.stat.is_adding_text,
                                isClickText: kag.stat.is_click_text
                            }
                        });
                    })();
                    """,
                    lambda result: print(f"[web-click] {result}", flush=True),
                )
            )
            autoclick.start()
        capture_path = os.environ.get("TYRANOR_WEB_CAPTURE", "")
        if capture_path:
            capture_delay = int(os.environ.get("TYRANOR_WEB_CAPTURE_DELAY_MS", "5000"))

            def capture() -> None:
                def save() -> None:
                    output = Path(capture_path).expanduser()
                    output.parent.mkdir(parents=True, exist_ok=True)
                    saved = view.grab().save(str(output))
                    print(f"[web-capture] path={output} saved={saved}", flush=True)
                    if os.environ.get("TYRANOR_WEB_EXIT_AFTER_CAPTURE") == "1":
                        app.quit()

                def state_received(state: object) -> None:
                    print(f"[web-state] {state}", flush=True)
                    QTimer.singleShot(100, save)

                view.page().runJavaScript(
                    """
                    (function () {
                        try {
                            var kag = window.TYRANO && TYRANO.kag;
                            return JSON.stringify({
                                title: document.title,
                                readyState: document.readyState,
                                clickLayers: $('.layer_event_click').length,
                                scenario: kag && kag.stat.current_scenario,
                                isWait: kag && kag.stat.is_wait,
                                isStop: kag && kag.stat.is_stop,
                                isAddingText: kag && kag.stat.is_adding_text,
                                isClickText: kag && kag.stat.is_click_text,
                                readyAudio: kag && kag.tmp.ready_audio,
                                isSwipe: kag && kag.key_mouse.is_swipe,
                                orderIndex: kag && kag.ftag.current_order_index,
                                hitTag: (document.elementFromPoint(
                                    innerWidth / 2, innerHeight / 2
                                ) || {}).tagName,
                                hitClass: (document.elementFromPoint(
                                    innerWidth / 2, innerHeight / 2
                                ) || {}).className,
                                clickHandlerCount: (function () {
                                    var element = $('.layer_event_click')[0];
                                    var data = element && $._data(element, 'events');
                                    return data && data.click ? data.click.length : 0;
                                })(),
                                titleButtons: $('img').filter(function () {
                                    return this.src.indexOf('/title/') !== -1;
                                }).map(function () {
                                    var rect = this.getBoundingClientRect();
                                    var events = $._data(this, 'events');
                                    return {
                                        src: this.getAttribute('src'),
                                        x: rect.x,
                                        y: rect.y,
                                        width: rect.width,
                                        height: rect.height,
                                        clicks: events && events.click ? events.click.length : 0
                                    };
                                }).get(),
                                titleHits: [[1062, 150], [1062, 250], [1062, 350], [1062, 450]].map(
                                    function (point) {
                                        var hit = document.elementFromPoint(point[0], point[1]);
                                        return {
                                            point: point,
                                            tag: hit && hit.tagName,
                                            src: hit && hit.getAttribute && hit.getAttribute('src'),
                                            className: hit && hit.className
                                        };
                                    }
                                ),
                                saveSlots: $('.save_display_area').map(function () {
                                    var events = $._data(this, 'events');
                                    var rect = this.getBoundingClientRect();
                                    return {
                                        num: $(this).attr('data-num'),
                                        clicks: events && events.click ? events.click.length : 0,
                                        x: rect.x,
                                        y: rect.y,
                                        width: rect.width,
                                        height: rect.height
                                    };
                                }).get(),
                                keydownHandlers: (function () {
                                    var data = $._data(document, 'events');
                                    return data && data.keydown ? data.keydown.length : 0;
                                })(),
                                currentTag: kag && kag.ftag.array_tag[
                                    kag.ftag.current_order_index
                                ],
                                bodyText: document.body.innerText.slice(0, 120)
                            });
                        } catch (error) {
                            return String(error && error.stack || error);
                        }
                    })();
                    """,
                    state_received,
                )

            QTimer.singleShot(capture_delay, capture)
        code = app.exec()
        server.shutdown()
        raise SystemExit(code)

    webbrowser.open(url)
    try:
        while not stop.wait(0.5):
            pass
    finally:
        server.shutdown()


def _resolve_entry(root: Path, explicit: str | None) -> Path | None:
    if explicit:
        candidate = (root / explicit).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return candidate
    for relative in ("index.html", "index.htm", "www/index.html", "www/index.htm", "game/index.html"):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    html_files = sorted(root.glob("*.html")) + sorted(root.glob("*.htm"))
    return html_files[0] if html_files else None


def _find_asar(root: Path) -> Path | None:
    for relative in ("app.asar", "resources/app.asar", "www/app.asar", "app/app.asar"):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return None


def _resolve_asar_entry(archive: AsarArchive, explicit: str | None) -> str | None:
    candidates = []
    if explicit:
        normalized = explicit.replace("\\", "/").lstrip("/")
        candidates.extend((normalized, f"{normalized}/index.html"))
    candidates.extend(
        (
            "index.html",
            "index.htm",
            "www/index.html",
            "www/index.htm",
            "app/index.html",
            "game/index.html",
        )
    )
    for candidate in candidates:
        if archive.exists(candidate):
            entry = archive.lookup_file(candidate)
            return entry.path if entry else None
    return None


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args,
        directory: str,
        entry: Path | str | None,
        archive: AsarArchive | None,
        storage_dir: Path,
        **kwargs,
    ):
        self.entry = entry
        self.archive = archive
        self.storage_dir = storage_dir
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:
        if self.path.startswith(_STORAGE_PREFIX):
            self._serve_storage(head=False)
            return
        if self.archive is not None:
            self._serve_asar(head=False)
            return
        if self.path == "/" and self.entry is not None:
            root = Path(self.directory).resolve()
            relative = self.entry.relative_to(root).as_posix()
            self.send_response(302)
            self.send_header("Location", "/" + urllib.parse.quote(relative))
            self.end_headers()
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.path.startswith(_STORAGE_PREFIX):
            self._serve_storage(head=True)
            return
        if self.archive is not None:
            self._serve_asar(head=True)
            return
        super().do_HEAD()

    def do_PUT(self) -> None:
        if not self.path.startswith(_STORAGE_PREFIX):
            self.send_error(405, "Method Not Allowed")
            return
        path = self._storage_path()
        if path is None:
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_error(411, "Content-Length required")
            return
        if length < 0 or length > _MAX_STORAGE_BYTES:
            self.send_error(413, "Storage value is too large")
            return
        payload = self.rfile.read(length)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            self.send_error(500, f"Could not store save data: {exc}")
            return
        self.send_response(204)
        self.end_headers()

    def _serve_asar(self, head: bool) -> None:
        assert self.archive is not None
        relative = urllib.parse.unquote(urllib.parse.urlparse(self.path).path).strip("/")
        if not relative and self.entry:
            relative = str(self.entry)
        entry = self.archive.lookup_file(relative)
        if entry is None:
            self.send_error(404, "ASAR entry not found")
            return
        content_type = mimetypes.guess_type(entry.path)[0] or "application/octet-stream"
        if entry.path == "tyrano/libs.js" and not self.headers.get("Range"):
            payload = self.archive.read(entry) + _TYRANO_STORAGE_SHIM
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            if not head:
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            return
        start = 0
        end = entry.size - 1
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                self.send_error(416, "Invalid Range")
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else entry.size - 1
            elif match.group(2):
                length = int(match.group(2))
                start = max(0, entry.size - length)
            if start > end or start >= entry.size:
                self.send_error(416, "Range Not Satisfiable")
                return
            end = min(end, entry.size - 1)
        length = max(0, end - start + 1)
        self.send_response(206 if range_header else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if range_header:
            self.send_header("Content-Range", f"bytes {start}-{end}/{entry.size}")
        self.end_headers()
        if head:
            return
        try:
            with self.archive.open_entry(entry) as stream:
                stream.seek(start if entry.unpacked else self.archive.data_offset + entry.offset + start)
                remaining = length
                while remaining:
                    block = stream.read(min(128 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
        except (OSError, AsarError, BrokenPipeError):
            return

    def _storage_path(self) -> Path | None:
        raw_key = self.path[len(_STORAGE_PREFIX) :].split("?", 1)[0]
        key = urllib.parse.unquote(raw_key)
        if not key:
            self.send_error(400, "Missing storage key")
            return None
        filename = urllib.parse.quote(key, safe="")
        if len(filename) > 180:
            filename = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.storage_dir / f"{filename}.sav"

    def _serve_storage(self, head: bool) -> None:
        path = self._storage_path()
        if path is None:
            return
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, "Storage value not found")
            return
        except OSError as exc:
            self.send_error(500, f"Could not read save data: {exc}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head:
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def translate_path(self, path: str) -> str:
        translated = super().translate_path(path)
        root = Path(self.directory).resolve()
        resolved = Path(translated).resolve()
        return str(resolved if resolved.is_relative_to(root) else root / "__not_found__")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        print(fmt % args, file=sys.stderr)


if __name__ == "__main__":
    main()
