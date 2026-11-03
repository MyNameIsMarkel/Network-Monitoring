"""Tema monocromo grafito: paleta, tipografías y hoja de estilos Qt."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from netmon.paths import resource_path

# Paleta (escala de grises con un ligero matiz frío, sin color de acento)
CANVAS = "#131518"     # fondo del visor
BASE = "#181B1F"       # fondo de la ventana / barra lateral
RAISED = "#20242A"     # campos, tarjetas
RAISED_HI = "#272C33"  # hover
LINE = "#30363D"       # bordes
LINE_HI = "#48505A"
TEXT = "#ECEEF0"
MUTED = "#959BA3"
FAINT = "#646B74"
WHITE = "#F7F8F9"
DOT = "#22262C"

UI_FONT = "Inter"
MONO_FONT = "JetBrains Mono"


def load_fonts() -> None:
    folder = resource_path("assets", "fonts")
    for f in sorted(folder.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(f))


def mono(size: int = 12) -> QFont:
    f = QFont(MONO_FONT)
    f.setPixelSize(size)
    f.setStyleHint(QFont.Monospace)
    return f


def apply(app: QApplication) -> None:
    load_fonts()
    app.setStyle("Fusion")
    font = QFont(UI_FONT)
    font.setPixelSize(13)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    pal = QPalette()
    for role, color in (
            (QPalette.Window, BASE), (QPalette.WindowText, TEXT), (QPalette.Base, RAISED),
            (QPalette.AlternateBase, BASE), (QPalette.Text, TEXT), (QPalette.Button, RAISED),
            (QPalette.ButtonText, TEXT), (QPalette.Highlight, "#3A414A"),
            (QPalette.HighlightedText, WHITE), (QPalette.ToolTipBase, "#0E1012"),
            (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, FAINT),
            (QPalette.Link, WHITE), (QPalette.BrightText, WHITE)):
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(FAINT))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(FAINT))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(FAINT))
    app.setPalette(pal)
    check = resource_path("assets", "check.svg").as_posix()
    arrow = resource_path("assets", "arrow.svg").as_posix()
    app.setStyleSheet(STYLESHEET.replace(":/check.svg", check).replace(":/arrow.svg", arrow))


STYLESHEET = f"""
* {{ outline: none; }}
QMainWindow, QWidget#root {{ background: {BASE}; }}
QToolTip {{
    background: #0E1012; color: {TEXT}; border: 1px solid {LINE};
    padding: 8px 10px; border-radius: 6px; font-size: 12px;
}}

/* ---------- barra lateral ---------- */
QWidget#sidebar {{ background: {BASE}; border-right: 1px solid {LINE}; }}
QScrollArea#sideScroll, QWidget#sideContent {{ background: transparent; border: none; }}
QLabel#brand {{ font-size: 15px; font-weight: 600; color: {WHITE}; letter-spacing: -0.2px; }}
QLabel#brandSub {{ color: {FAINT}; font-size: 12px; }}
QLabel#section {{ color: {MUTED}; font-size: 12px; font-weight: 600; padding-top: 6px; }}
QLabel#hint {{ color: {FAINT}; font-size: 12px; }}
QLabel#fieldLabel {{ color: {MUTED}; font-size: 12px; }}
QLabel#path {{ color: {TEXT}; font-size: 12px; }}

/* ---------- campos ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; border-radius: 7px;
    padding: 7px 10px; selection-background-color: #3A414A; min-height: 18px;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {LINE_HI}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {MUTED}; }}
QLineEdit:disabled {{ color: {FAINT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url(:/arrow.svg); width: 10px; height: 6px; margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {RAISED}; border: 1px solid {LINE}; color: {TEXT};
    selection-background-color: {RAISED_HI}; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QCheckBox {{ color: {TEXT}; spacing: 9px; font-size: 13px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {LINE_HI};
    background: {RAISED}; }}
QCheckBox::indicator:hover {{ border-color: {MUTED}; }}
QCheckBox::indicator:checked {{ background: {WHITE}; border-color: {WHITE};
    image: url(:/check.svg); }}

/* ---------- botones ---------- */
QPushButton {{
    background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; border-radius: 7px;
    padding: 7px 13px; font-size: 13px;
}}
QPushButton:hover {{ background: {RAISED_HI}; border-color: {LINE_HI}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: {RAISED_HI}; }}
QPushButton#primary {{
    background: {WHITE}; color: #15171A; border: none; border-radius: 9px;
    padding: 12px 16px; font-size: 14px; font-weight: 600;
}}
QPushButton#primary:hover {{ background: #FFFFFF; }}
QPushButton#primary:pressed {{ background: #D9DCE0; }}
QPushButton#danger {{
    background: transparent; color: {TEXT}; border: 1px solid {LINE_HI}; border-radius: 9px;
    padding: 12px 16px; font-size: 14px; font-weight: 600;
}}
QPushButton#danger:hover {{ background: {RAISED}; }}
QPushButton#ghost {{ background: transparent; border: none; color: {MUTED}; padding: 6px 8px; }}
QPushButton#ghost:hover {{ color: {WHITE}; }}
QPushButton#seg {{
    background: transparent; border: 1px solid transparent; color: {MUTED}; border-radius: 7px;
    padding: 6px 12px;
}}
QPushButton#seg:hover {{ color: {TEXT}; }}
QPushButton#seg:checked {{ background: {RAISED}; border-color: {LINE}; color: {WHITE}; }}
QPushButton#tool {{
    background: transparent; border: 1px solid {LINE}; color: {TEXT}; border-radius: 7px;
    padding: 6px 11px; font-size: 12px;
}}
QPushButton#tool:hover {{ background: {RAISED}; border-color: {LINE_HI}; }}
QPushButton#tool:disabled {{ color: {FAINT}; border-color: {RAISED}; }}
QPushButton#disclosure {{ background: transparent; border: none; color: {MUTED}; text-align: left;
    padding: 6px 0; font-size: 12px; font-weight: 600; }}
QPushButton#disclosure:hover {{ color: {TEXT}; }}

QFrame#segBox {{ background: {BASE}; border: 1px solid {LINE}; border-radius: 9px; }}

/* ---------- zona principal ---------- */
QWidget#topbar {{ background: {BASE}; border-bottom: 1px solid {LINE}; }}
QLabel#fileName {{ color: {MUTED}; font-size: 12px; }}
QWidget#statusbar {{ background: {BASE}; border-top: 1px solid {LINE}; }}
QLabel#status {{ color: {MUTED}; font-size: 12px; }}
QProgressBar {{ background: {RAISED}; border: none; border-radius: 2px; max-height: 4px; }}
QProgressBar::chunk {{ background: {WHITE}; border-radius: 2px; }}

QFrame#floating {{ background: rgba(24,27,31,235); border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#floating QPushButton {{ background: transparent; border: none; color: {TEXT};
    padding: 6px 10px; border-radius: 6px; }}
QFrame#floating QPushButton:hover {{ background: {RAISED_HI}; }}
QLabel#zoomLabel {{ color: {MUTED}; font-size: 12px; min-width: 44px; }}
QLabel#detailTitle {{ color: {WHITE}; font-size: 14px; font-weight: 600; }}
QLabel#detailKind {{ color: {MUTED}; font-size: 12px; }}
QLabel#detailKey {{ color: {FAINT}; font-size: 12px; }}
QLabel#detailVal {{ color: {TEXT}; font-size: 12px; }}

QLabel#emptyTitle {{ color: {TEXT}; font-size: 20px; font-weight: 600; letter-spacing: -0.3px; }}
QLabel#emptyText {{ color: {MUTED}; font-size: 13px; }}

QTableWidget {{ background: {BASE}; alternate-background-color: #1B1F23; color: {TEXT};
    border: none; gridline-color: transparent; selection-background-color: {RAISED_HI};
    selection-color: {WHITE}; font-size: 12px; }}
QTableWidget::item {{ padding: 6px 10px; border-bottom: 1px solid #1F2328; }}
QHeaderView::section {{ background: {BASE}; color: {MUTED}; border: none;
    border-bottom: 1px solid {LINE}; padding: 9px 10px; font-size: 12px; font-weight: 600; }}
QTableCornerButton::section {{ background: {BASE}; border: none; }}

QPlainTextEdit#log {{ background: {CANVAS}; color: {TEXT}; border: none; padding: 14px 18px;
    selection-background-color: #3A414A; }}

QListWidget#history {{ background: {BASE}; border: none; color: {TEXT}; padding: 8px; }}
QListWidget#history::item {{ border: 1px solid transparent; border-radius: 8px; padding: 0; margin: 2px 8px; }}
QListWidget#history::item:hover {{ background: {RAISED}; }}
QListWidget#history::item:selected {{ background: {RAISED_HI}; border-color: {LINE}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {LINE_HI}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QMessageBox {{ background: {BASE}; }}
QMenu {{ background: {RAISED}; border: 1px solid {LINE}; color: {TEXT}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: {RAISED_HI}; }}
"""
