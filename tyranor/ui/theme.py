from __future__ import annotations

import random
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPalette, QRadialGradient
from PyQt6.QtWidgets import QApplication, QWidget


PALETTES = {
    "light": {
        "bg": "#F1F4F8",
        "surface": "#FFFFFF",
        "surface_alt": "#EEF2F7",
        "text": "#202838",
        "muted": "#707A8C",
        "border": "#DDE3EA",
        "shadow": "rgba(30, 41, 59, 0.12)",
    },
    "dark": {
        "bg": "#11161F",
        "surface": "#1B2230",
        "surface_alt": "#242D3D",
        "text": "#EEF3FA",
        "muted": "#A1ACBE",
        "border": "#303A4B",
        "shadow": "rgba(0, 0, 0, 0.30)",
    },
}


def is_dark(settings) -> bool:
    mode = settings.get("appearance_mode", "system")
    if settings.get("appearance_style") == "glass":
        return True
    if settings.get("appearance_style") == "milk":
        return False
    if mode == "dark":
        return True
    if mode == "light":
        return False
    app = QApplication.instance()
    if app is not None:
        return app.palette().color(app.palette().ColorRole.Window).lightness() < 128
    return False


def palette(settings) -> dict[str, str]:
    if settings.get("appearance_style") == "glass":
        values = dict(PALETTES["dark"])
        values["bg"] = "#172432"
        values["surface"] = "#263544"
        values["surface_alt"] = "#304253"
        return values
    if settings.get("appearance_style") == "milk":
        values = dict(PALETTES["light"])
        values["bg"] = "#EEF1F5"
        values["surface"] = "rgba(255, 255, 255, 235)"
        values["surface_alt"] = "rgba(240, 244, 249, 235)"
        return values
    return PALETTES["dark" if is_dark(settings) else "light"]


def stylesheet(settings) -> str:
    colors = palette(settings)
    accent = settings.get("accent", "#5B8DEF")
    radius = int(settings.get("corner_radius", 15))
    small = max(5, min(12, radius))
    return f"""
    QWidget {{
        color: {colors['text']};
        font-family: "Noto Sans CJK SC", "Noto Sans", sans-serif;
        font-size: 14px;
    }}
    QMainWindow, QWidget#Root {{
        background: {colors['bg']};
    }}
    QWidget#Sidebar {{
        background: {colors['surface']};
        border-right: 1px solid {colors['border']};
    }}
    QLabel#PageTitle {{
        font-size: 28px;
        font-weight: 700;
        letter-spacing: 0.2px;
    }}
    QLabel#SectionTitle {{
        font-size: 18px;
        font-weight: 700;
    }}
    QLabel#HeroTitle {{
        font-size: 25px;
        font-weight: 700;
    }}
    QLabel#Muted {{
        color: {colors['muted']};
    }}
    QLabel#Badge {{
        color: {accent};
        background: {QColor(accent).lighter(185).name() if is_dark(settings) else QColor(accent).lighter(230).name()};
        border-radius: {small}px;
        padding: 3px 8px;
        font-size: 12px;
        font-weight: 600;
    }}
    QFrame#Card, QWidget#Card {{
        background: {colors['surface']};
        border: 1px solid {colors['border']};
        border-radius: {radius}px;
    }}
    QFrame#SoftCard {{
        background: {colors['surface_alt']};
        border: 1px solid {colors['border']};
        border-radius: {radius}px;
    }}
    QPushButton {{
        background: {colors['surface_alt']};
        border: 1px solid {colors['border']};
        border-radius: {small}px;
        padding: 8px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        border-color: {accent};
    }}
    QPushButton:pressed {{
        background: {colors['border']};
    }}
    QPushButton#Primary {{
        color: white;
        background: {accent};
        border: none;
        padding: 9px 18px;
        font-weight: 700;
    }}
    QPushButton#Primary:hover {{
        background: {QColor(accent).lighter(112).name()};
    }}
    QPushButton#Danger {{
        color: #C94D5B;
    }}
    QPushButton#NavButton {{
        color: {colors['muted']};
        background: transparent;
        border: none;
        border-radius: {radius}px;
        text-align: left;
        padding: 11px 14px;
        font-size: 15px;
    }}
    QPushButton#NavButton:hover {{
        color: {colors['text']};
        background: {colors['surface_alt']};
    }}
    QPushButton#NavButton:checked {{
        color: {accent};
        background: {QColor(accent).lighter(220).name() if not is_dark(settings) else QColor(accent).darker(260).name()};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {colors['surface_alt']};
        border: 1px solid {colors['border']};
        border-radius: {small}px;
        padding: 7px 10px;
        selection-background-color: {accent};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border-color: {accent};
    }}
    QListWidget, QTreeWidget, QTableWidget {{
        background: {colors['surface']};
        border: 1px solid {colors['border']};
        border-radius: {radius}px;
        outline: none;
    }}
    QListWidget::item, QTreeWidget::item {{
        padding: 9px;
        border-radius: {small}px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        color: {colors['text']};
        background: {colors['surface_alt']};
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {colors['border']};
        min-height: 28px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QMenu {{
        background: {colors['surface']};
        border: 1px solid {colors['border']};
        border-radius: {small}px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 8px 26px 8px 12px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background: {colors['surface_alt']};
        color: {accent};
    }}
    QTabWidget::pane {{
        border: 1px solid {colors['border']};
        border-radius: {radius}px;
        background: {colors['surface']};
    }}
    QTabBar::tab {{
        padding: 9px 18px;
        color: {colors['muted']};
    }}
    QTabBar::tab:selected {{
        color: {accent};
        font-weight: 700;
    }}
    QProgressBar {{
        height: 8px;
        border: none;
        background: {colors['surface_alt']};
        border-radius: 4px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: {accent};
        border-radius: 4px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
    }}
    QToolTip {{
        color: {colors['text']};
        background: {colors['surface']};
        border: 1px solid {colors['border']};
        padding: 5px;
    }}
    """


class ParticlesOverlay(QWidget):
    def __init__(self, parent: QWidget, settings):
        super().__init__(parent)
        self.settings = settings
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._points = [self._new_point() for _ in range(28)]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)
        self._tick()

    def _new_point(self) -> dict:
        return {
            "x": random.random(),
            "y": random.random(),
            "radius": random.uniform(1.2, 3.5),
            "speed": random.uniform(0.00015, 0.00055),
            "phase": random.random() * 6.28,
        }

    def _tick(self) -> None:
        if not self.settings.get("particles", True):
            self.hide()
            return
        self.show()
        for point in self._points:
            point["y"] -= point["speed"]
            point["x"] += 0.00004
            if point["y"] < -0.03:
                point.update(self._new_point())
                point["y"] = 1.03
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(self.settings.get("accent", "#5B8DEF"))
        accent.setAlpha(42)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        for point in self._points:
            painter.drawEllipse(
                QPointF(point["x"] * self.width(), point["y"] * self.height()),
                point["radius"],
                point["radius"],
            )


class GradientRoot(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.particles = ParticlesOverlay(self, settings)
        self.setObjectName("Root")

    def resizeEvent(self, event) -> None:
        self.particles.setGeometry(self.rect())
        self.particles.raise_()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        style = self.settings.get("appearance_style", "default")
        if style == "glass":
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0, QColor("#12202D"))
            gradient.setColorAt(0.55, QColor("#243445"))
            gradient.setColorAt(1, QColor("#1D2938"))
            painter.fillRect(self.rect(), gradient)
            glow = QRadialGradient(self.width() * 0.72, self.height() * 0.16, self.width() * 0.45)
            accent = QColor(self.settings.get("accent", "#5B8DEF"))
            accent.setAlpha(34)
            glow.setColorAt(0, accent)
            glow.setColorAt(1, Qt.GlobalColor.transparent)
            painter.fillRect(self.rect(), glow)
        elif style == "milk":
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0, QColor("#F5F7FA"))
            gradient.setColorAt(0.55, QColor("#E8EEF5"))
            gradient.setColorAt(1, QColor("#D9E3EE"))
            painter.fillRect(self.rect(), gradient)
            accent = QColor(self.settings.get("accent", "#5B8DEF"))
            accent.setAlpha(18)
            painter.fillRect(QRectF(0, 0, self.width() * 0.65, self.height() * 0.4), accent)
        else:
            painter.fillRect(self.rect(), QColor(palette(self.settings)["bg"]))


def apply_theme(app: QApplication, settings) -> None:
    app.setStyle("Fusion")
    colors = palette(settings)
    app_palette = app.palette()
    values = {
        QPalette.ColorRole.Window: QColor(colors["bg"]),
        QPalette.ColorRole.WindowText: QColor(colors["text"]),
        QPalette.ColorRole.Base: QColor(colors["surface"]),
        QPalette.ColorRole.AlternateBase: QColor(colors["surface_alt"]),
        QPalette.ColorRole.Text: QColor(colors["text"]),
        QPalette.ColorRole.Button: QColor(colors["surface"]),
        QPalette.ColorRole.ButtonText: QColor(colors["text"]),
        QPalette.ColorRole.ToolTipBase: QColor(colors["surface"]),
        QPalette.ColorRole.ToolTipText: QColor(colors["text"]),
        QPalette.ColorRole.PlaceholderText: QColor(colors["muted"]),
        QPalette.ColorRole.Highlight: QColor(settings.get("accent", "#5B8DEF")),
        QPalette.ColorRole.HighlightedText: QColor("#FFFFFF"),
    }
    for role, color in values.items():
        app_palette.setColor(role, color)
    app.setPalette(app_palette)
    app.setStyleSheet(stylesheet(settings))
    font = QFont("Noto Sans CJK SC", 10)
    app.setFont(font)
