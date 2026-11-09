from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, Qt


def prepare_qtwebengine() -> bool:
    """Prepare Qt's WebEngine globals before the first QApplication exists."""
    if QCoreApplication.instance() is None:
        QCoreApplication.setAttribute(
            Qt.ApplicationAttribute.AA_ShareOpenGLContexts,
            True,
        )
    try:
        import PyQt6.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        return False
    return True


QWEBENGINE_AVAILABLE = prepare_qtwebengine()

if QWEBENGINE_AVAILABLE:
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView
else:
    QWebEnginePage = None  # type: ignore[assignment,misc]
    QWebEngineProfile = None  # type: ignore[assignment,misc]
    QWebEngineView = None  # type: ignore[assignment,misc]
