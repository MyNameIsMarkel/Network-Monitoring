"""Widgets propios: tarjetas de modo con medidor de impacto, logotipo y ayudantes de maquetación."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from netmon.paths import resource_path
from netmon.ui import theme


class Logo(QWidget):
    def __init__(self, size: int = 34, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._r = QSvgRenderer(str(resource_path("assets", "icon.svg")))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._r.render(p, QRectF(0, 0, self.width(), self.height()))


class ModeCard(QWidget):
    """Tarjeta seleccionable. El medidor de barras muestra el impacto en la red (1–5)."""
    clicked = Signal()

    def __init__(self, title: str, body: str, impact: int, impact_text: str, parent=None):
        super().__init__(parent)
        self.title, self.body = title, body
        self.impact, self.impact_text = impact, impact_text
        self.checked = False
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(self._height_for(300))

    def _height_for(self, width: int) -> int:
        f = QFont(self.font())
        f.setPixelSize(12)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        r = fm.boundingRect(0, 0, max(120, width - 36), 400, Qt.TextWordWrap, self.body)
        return 16 + 20 + 8 + r.height() + 14 + 18 + 16

    def resizeEvent(self, e):
        self.setMinimumHeight(self._height_for(self.width()))
        super().resizeEvent(e)

    def setChecked(self, v: bool) -> None:
        self.checked = v
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        bg = QColor(theme.RAISED if (self.checked or self._hover) else theme.BASE)
        border = QColor(theme.WHITE if self.checked else
                        (theme.LINE_HI if self._hover or self.hasFocus() else theme.LINE))
        p.setPen(QPen(border, 1.5 if self.checked else 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 10, 10)

        # indicador de selección (círculo)
        cx, cy = r.right() - 22, r.top() + 24
        p.setPen(QPen(QColor(theme.WHITE if self.checked else theme.LINE_HI), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(cx - 7, cy - 7, 14, 14))
        if self.checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.WHITE))
            p.drawEllipse(QRectF(cx - 3.5, cy - 3.5, 7, 7))

        left = r.left() + 16
        f = QFont(self.font())
        f.setPixelSize(14)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(theme.WHITE if self.checked else theme.TEXT))
        p.drawText(QRectF(left, r.top() + 14, r.width() - 60, 22), Qt.AlignVCenter, self.title)

        f.setPixelSize(12)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        body_rect = QRectF(left, r.top() + 42, r.width() - 34, r.height() - 42 - 36)
        p.drawText(body_rect, Qt.TextWordWrap | Qt.AlignTop, self.body)

        # medidor de impacto: 5 barras crecientes
        base_y = r.bottom() - 15
        x = left
        for i in range(5):
            h = 5 + i * 2.5
            on = i < self.impact
            p.setPen(Qt.NoPen)
            col = QColor(theme.WHITE if self.checked else theme.TEXT) if on else QColor(theme.LINE)
            if on and not self.checked:
                col.setAlpha(170)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, base_y - h, 4, h), 1.2, 1.2)
            x += 7
        p.setPen(QColor(theme.TEXT if self.checked else theme.MUTED))
        p.drawText(QRectF(x + 6, base_y - 15, 200, 16), Qt.AlignVCenter, self.impact_text)


def section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("fieldLabel")
    return lbl


def hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("hint")
    lbl.setWordWrap(True)
    return lbl


def vbox(*widgets, spacing: int = 6, margins=(0, 0, 0, 0)) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for x in widgets:
        if isinstance(x, QWidget):
            lay.addWidget(x)
        else:
            lay.addLayout(x)
    return w
