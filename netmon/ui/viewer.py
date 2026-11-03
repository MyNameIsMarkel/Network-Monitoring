"""Visor integrado de ficheros .drawio (sin navegador ni conexión a Internet).

Dibuja con QGraphicsScene los elementos que usa draw.io de forma habitual: imágenes (SVG/PNG
incrustados), rectángulos, elipses, textos HTML, líneas y conectores con puntos de paso,
estilos discontinuos y etiquetas de conector.
"""
from __future__ import annotations

import base64
import html
import math
import re
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QTextOption)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (QGraphicsDropShadowEffect, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsTextItem, QGraphicsView)

from netmon.drawio.reader import Cell, Page, absolute_origin, read_drawio

FONT_MAP = {"helvetica": "Inter", "arial": "Inter", "verdana": "Inter"}


def _color(value: str, default: str | None) -> QColor | None:
    v = (value or "").strip()
    if not v:
        return QColor(default) if default else None
    if v.lower() == "none":
        return None
    c = QColor(v)
    return c if c.isValid() else (QColor(default) if default else None)


def _image_bytes(uri: str) -> tuple[bytes, str] | None:
    if not uri.startswith("data:"):
        return None
    head, _, payload = uri.partition(",")
    kind = "svg" if "svg" in head else "raster"
    try:
        if ";base64" in head or not payload.lstrip().startswith("<"):
            return base64.b64decode(payload + "=" * (-len(payload) % 4)), kind
        return urllib.parse.unquote(payload).encode(), kind
    except Exception:
        return None


class NodeItem(QGraphicsRectItem):
    """Zona clicable de un dispositivo (transparente) que guarda sus atributos."""

    def __init__(self, rect: QRectF, cell: Cell):
        super().__init__(rect)
        self.cell = cell
        self.setPen(QPen(Qt.NoPen))
        self.setBrush(QBrush(Qt.transparent))
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        tip = cell.attrs.get("tooltip", "")
        if tip:
            self.setToolTip(tip)
        self._hover = False

    def hoverEnterEvent(self, e):
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, e):
        self._hover = False
        self.update()

    def paint(self, painter, option, widget=None):
        if self._hover or self.isSelected():
            painter.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor("#1F2328"), 1.4, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(-6, -6, 6, 6), 10, 10)


class DiagramView(QGraphicsView):
    zoomChanged = Signal(int)
    nodeSelected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing |
                            QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self._svg_cache: dict[str, QSvgRenderer] = {}
        self._paper: QGraphicsRectItem | None = None
        self.path: Path | None = None
        self.page: Page | None = None
        self._canvas = QColor("#121417")
        self._dot = QColor("#24282E")

    def set_canvas_colors(self, bg: str, dot: str) -> None:
        self._canvas, self._dot = QColor(bg), QColor(dot)
        self.viewport().update()

    # ------------------------------------------------------------ carga
    def clear(self) -> None:
        self.scene().clear()
        self._paper = None
        self.path = None
        self.page = None

    def load(self, path: str | Path) -> None:
        pages = read_drawio(path)
        if not pages:
            raise ValueError("El fichero no contiene ningún diagrama")
        self.clear()
        self.path = Path(path)
        self.page = pages[0]
        self._render(self.page)
        self.fit()

    def _render(self, page: Page) -> None:
        scene = self.scene()
        bounds = QRectF()
        edges: list[Cell] = []
        labels: list[Cell] = []
        z = 0
        edge_z: dict[str, int] = {}
        for cid in page.order:
            c = page.cells[cid]
            if c.edge:
                edges.append(c)
                edge_z[cid] = z
                z += 1
            elif c.vertex:
                parent = page.cells.get(c.parent or "")
                if parent is not None and parent.edge:
                    labels.append(c)
                    continue
                r = self._draw_vertex(page, c, z)
                z += 1
                if r is not None:
                    bounds = bounds.united(r)
        edge_paths: dict[str, list[QPointF]] = {}
        for c in edges:
            pts = self._edge_points(page, c)
            if len(pts) >= 2:
                edge_paths[c.id] = pts
                self._draw_edge(c, pts, edge_z.get(c.id, -10))
                for p in pts:
                    bounds = bounds.united(QRectF(p, p).adjusted(-2, -2, 2, 2))
        for c in labels:
            pts = edge_paths.get(c.parent or "")
            if pts:
                self._draw_edge_label(c, pts)
        if bounds.isNull():
            bounds = QRectF(0, 0, 800, 600)
        paper_rect = bounds.adjusted(-36, -36, 36, 36)
        bg = _color(page.background, "#FFFFFF") or QColor("#FFFFFF")
        paper = QGraphicsRectItem(paper_rect)
        paper.setBrush(QBrush(bg))
        paper.setPen(QPen(Qt.NoPen))
        paper.setZValue(-1000)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 150))
        paper.setGraphicsEffect(shadow)
        scene.addItem(paper)
        self._paper = paper
        scene.setSceneRect(paper_rect.adjusted(-2000, -2000, 2000, 2000))

    # ------------------------------------------------------------ vértices
    def _abs_rect(self, page: Page, c: Cell) -> QRectF:
        x, y = absolute_origin(page, c)
        return QRectF(x, y, c.geometry.width, c.geometry.height)

    def _draw_vertex(self, page: Page, c: Cell, z: int) -> QRectF | None:
        rect = self._abs_rect(page, c)
        shape = c.get("shape") or c.style_name
        scene = self.scene()
        covered = QRectF(rect)
        if c.style_name in ("group",) or c.get("visible") == "0":
            return None
        if shape == "image" or c.style_name == "image":
            self._draw_image(c, rect, z)
        elif shape == "line":
            pen = QPen(_color(c.get("strokeColor"), "#000000") or QColor("#000"),
                       c.num("strokeWidth", 1))
            item = scene.addLine(rect.left(), rect.center().y(), rect.right(), rect.center().y(), pen)
            item.setZValue(z)
        elif c.style_name == "text" or c.get("text") == "1":
            pass
        elif c.style_name not in ("edgeLabel",):
            self._draw_shape(c, rect, z, shape)
        if c.value:
            lr = self._draw_label(c, rect, z + 0.5)
            if lr is not None:
                covered = covered.united(lr)
        if c.attrs.get("nm_type") or c.attrs.get("tooltip"):
            node = NodeItem(rect, c)
            node.setZValue(z + 0.6)
            node.setFlag(QGraphicsItem.ItemIsSelectable, True)
            scene.addItem(node)
        return covered

    def _draw_shape(self, c: Cell, rect: QRectF, z: int, shape: str) -> None:
        fill = _color(c.get("fillColor"), "#FFFFFF")
        stroke = _color(c.get("strokeColor"), "#000000")
        pen = QPen(stroke, c.num("strokeWidth", 1)) if stroke else QPen(Qt.NoPen)
        if c.get("dashed") == "1" and stroke:
            pen.setStyle(Qt.DashLine)
        brush = QBrush(fill) if fill else QBrush(Qt.NoBrush)
        path = QPainterPath()
        if shape == "ellipse" or c.style_name == "ellipse":
            path.addEllipse(rect)
        elif shape == "rhombus" or c.style_name == "rhombus":
            path.addPolygon(QPolygonF([QPointF(rect.center().x(), rect.top()),
                                       QPointF(rect.right(), rect.center().y()),
                                       QPointF(rect.center().x(), rect.bottom()),
                                       QPointF(rect.left(), rect.center().y()),
                                       QPointF(rect.center().x(), rect.top())]))
        elif c.get("rounded") == "1":
            arc = c.num("arcSize", 15)
            r = min(rect.width(), rect.height()) * arc / 100
            path.addRoundedRect(rect, r, r)
        else:
            path.addRect(rect)
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        item.setBrush(brush)
        item.setZValue(z)
        self.scene().addItem(item)

    def _draw_image(self, c: Cell, rect: QRectF, z: int) -> None:
        uri = c.get("image")
        data = _image_bytes(uri)
        if data is None:
            self._draw_shape(c, rect, z, "rect")
            return
        raw, kind = data
        if kind == "svg":
            renderer = self._svg_cache.get(uri)
            if renderer is None:
                renderer = QSvgRenderer(QByteArray(raw))
                self._svg_cache[uri] = renderer
            item = QGraphicsSvgItem()
            item.setSharedRenderer(renderer)
            size = renderer.defaultSize()
            sw, sh = max(1, size.width()), max(1, size.height())
        else:
            img = QImage.fromData(raw)
            item = QGraphicsPixmapItem(QPixmap.fromImage(img))
            item.setTransformationMode(Qt.SmoothTransformation)
            sw, sh = max(1, img.width()), max(1, img.height())
        scale = min(rect.width() / sw, rect.height() / sh)
        if c.get("imageAspect") == "0":
            item.setTransform(item.transform().scale(rect.width() / sw, rect.height() / sh))
            item.setPos(rect.topLeft())
        else:
            item.setScale(scale)
            item.setPos(rect.center().x() - sw * scale / 2, rect.center().y() - sh * scale / 2)
        item.setZValue(z)
        self.scene().addItem(item)

    def _text_item(self, c: Cell, max_width: float | None, default_size: float,
                   default_color: str) -> QGraphicsTextItem:
        item = QGraphicsTextItem()
        family = c.get("fontFamily", "Helvetica")
        fam = FONT_MAP.get(family.lower(), family)
        font = QFont(fam)
        font.setPixelSize(int(c.num("fontSize", default_size)))
        style_bits = int(c.num("fontStyle", 0))
        font.setBold(bool(style_bits & 1))
        font.setItalic(bool(style_bits & 2))
        item.setFont(font)
        item.setDefaultTextColor(_color(c.get("fontColor"), default_color) or QColor(default_color))
        doc = item.document()
        doc.setDocumentMargin(1)
        opt = QTextOption()
        align = c.get("align", "center")
        opt.setAlignment({"left": Qt.AlignLeft, "right": Qt.AlignRight}.get(align, Qt.AlignHCenter))
        doc.setDefaultTextOption(opt)
        value = c.value
        if c.is_html:
            value = re.sub(r"(?i)<div([^>]*)>", r"<p\1 style='margin:0'>", value)
            value = re.sub(r"(?i)</div>", "</p>", value)
            item.setHtml(value)
        else:
            item.setPlainText(html.unescape(value))
        if max_width:
            item.setTextWidth(max_width)
            ideal = doc.idealWidth()
            if ideal < max_width - 1:
                item.setTextWidth(math.ceil(ideal) + 2)
        return item

    def _draw_label(self, c: Cell, rect: QRectF, z: float) -> QRectF | None:
        wrap = c.get("whiteSpace") == "wrap"
        item = self._text_item(c, rect.width() if wrap and rect.width() > 4 else None, 12,
                               "#000000")
        br = item.boundingRect()
        align = c.get("align", "center")
        valign = c.get("verticalAlign", "middle")
        spacing_top = c.num("spacingTop", 0)
        if c.get("verticalLabelPosition") == "bottom":
            y = rect.bottom() + spacing_top
        elif c.get("verticalLabelPosition") == "top":
            y = rect.top() - br.height()
        elif valign == "top":
            y = rect.top() + spacing_top
        elif valign == "bottom":
            y = rect.bottom() - br.height()
        else:
            y = rect.center().y() - br.height() / 2
        if align == "left":
            x = rect.left() + c.num("spacingLeft", 0)
        elif align == "right":
            x = rect.right() - br.width()
        else:
            x = rect.center().x() - br.width() / 2
        item.setPos(x, y)
        item.setZValue(z)
        bg = _color(c.get("labelBackgroundColor"), None)
        if bg is not None:
            back = QGraphicsRectItem(QRectF(x, y, br.width(), br.height()).adjusted(0, 1, 0, -1))
            back.setBrush(QBrush(bg))
            back.setPen(QPen(Qt.NoPen))
            back.setZValue(z - 0.1)
            self.scene().addItem(back)
        self.scene().addItem(item)
        return QRectF(x, y, br.width(), br.height())

    # ------------------------------------------------------------ conectores
    def _edge_points(self, page: Page, c: Cell) -> list[QPointF]:
        g = c.geometry
        src = page.cells.get(c.source or "")
        trg = page.cells.get(c.target or "")
        sr = self._abs_rect(page, src) if src is not None and src.vertex else None
        tr = self._abs_rect(page, trg) if trg is not None and trg.vertex else None
        pts = [QPointF(x, y) for x, y in g.points]

        def anchor(r: QRectF | None, fixed, kx, ky, toward: QPointF | None) -> QPointF | None:
            if r is None:
                return QPointF(*fixed) if fixed else None
            if c.get(kx) != "":
                return QPointF(r.left() + float(c.get(kx)) * r.width() + c.num(kx[:-1] + "Dx", 0),
                               r.top() + float(c.get(ky)) * r.height() + c.num(ky[:-1] + "Dy", 0))
            if toward is None:
                return r.center()
            return _perimeter(r, toward)

        if not pts and c.get("edgeStyle") in ("orthogonalEdgeStyle", "elbowEdgeStyle") \
                and sr is not None and tr is not None:
            return _elbow(sr, tr)
        first = pts[0] if pts else (tr.center() if tr is not None else
                                    (QPointF(*g.target_point) if g.target_point else None))
        last = pts[-1] if pts else (sr.center() if sr is not None else
                                    (QPointF(*g.source_point) if g.source_point else None))
        start = anchor(sr, g.source_point, "exitX", "exitY", first)
        end = anchor(tr, g.target_point, "entryX", "entryY", last)
        out = ([start] if start else []) + pts + ([end] if end else [])
        return out

    def _draw_edge(self, c: Cell, pts: list[QPointF], z: float = -10) -> None:
        stroke = _color(c.get("strokeColor"), "#000000")
        if stroke is None:
            return
        width = c.num("strokeWidth", 1)
        pen = QPen(stroke, width)
        pen.setCapStyle(Qt.FlatCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if c.get("dashed") == "1":
            pattern = [float(x) for x in (c.get("dashPattern") or "3 3").split() if x]
            pen.setDashPattern([max(0.5, p / max(width, 0.5)) for p in pattern] or [3, 3])
        radius = 8.0 if c.get("rounded") == "1" else 0.0
        path = _rounded_path(pts, radius)
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        item.setZValue(z)
        self.scene().addItem(item)
        for which, a, b in (("endArrow", pts[-2], pts[-1]), ("startArrow", pts[1], pts[0])):
            kind = c.get(which, "classic" if which == "endArrow" else "none")
            if kind and kind != "none":
                self._arrow(a, b, stroke, width, c.get(which.replace("Arrow", "Fill")) != "0", z)
        if c.value:
            mid = _point_at(pts, _path_len(pts) / 2)
            self._floating_label(c, mid, 11)

    def _arrow(self, a: QPointF, b: QPointF, color: QColor, width: float, filled: bool,
               z: float = -9) -> None:
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        size = 6 + width * 1.5
        p1 = QPointF(b.x() - size * math.cos(ang - 0.4), b.y() - size * math.sin(ang - 0.4))
        p2 = QPointF(b.x() - size * math.cos(ang + 0.4), b.y() - size * math.sin(ang + 0.4))
        path = QPainterPath()
        path.addPolygon(QPolygonF([b, p1, p2, b]))
        item = QGraphicsPathItem(path)
        item.setPen(QPen(color, 1))
        item.setBrush(QBrush(color) if filled else QBrush(Qt.white))
        item.setZValue(z + 0.1)
        self.scene().addItem(item)

    def _draw_edge_label(self, c: Cell, pts: list[QPointF]) -> None:
        total = _path_len(pts)
        rel = c.geometry.x if c.geometry.relative else 0
        p = _point_at(pts, (rel + 1) / 2 * total)
        ox, oy = c.geometry.offset
        self._floating_label(c, QPointF(p.x() + ox, p.y() + oy), 11)

    def _floating_label(self, c: Cell, center: QPointF, size: float) -> None:
        item = self._text_item(c, None, size, "#000000")
        br = item.boundingRect()
        x, y = center.x() - br.width() / 2, center.y() - br.height() / 2
        item.setPos(x, y)
        item.setZValue(100000)
        bg = _color(c.get("labelBackgroundColor"), "#FFFFFF")
        if bg is not None:
            back = QGraphicsRectItem(QRectF(x, y, br.width(), br.height()).adjusted(1, 1, -1, -1))
            back.setBrush(QBrush(bg))
            back.setPen(QPen(Qt.NoPen))
            back.setZValue(99999)
            self.scene().addItem(back)
        self.scene().addItem(item)

    # ------------------------------------------------------------ interacción
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, self._canvas)
        step = 24
        left = math.floor(rect.left() / step) * step
        top = math.floor(rect.top() / step) * step
        scale = self.transform().m11()
        if scale * step < 9:
            return
        painter.setPen(QPen(self._dot, 1.6 / max(scale, 0.01)))
        y = top
        pts = []
        while y < rect.bottom():
            x = left
            while x < rect.right():
                pts.append(QPointF(x, y))
                x += step
            y += step
        painter.drawPoints(pts)

    def wheelEvent(self, e) -> None:
        delta = e.angleDelta().y()
        if delta == 0:
            return
        self.zoom_by(1.0015 ** delta)

    def zoom_by(self, factor: float) -> None:
        cur = self.transform().m11()
        target = max(0.08, min(6.0, cur * factor))
        f = target / cur
        self.scale(f, f)
        self.zoomChanged.emit(round(target * 100))

    def set_zoom(self, pct: float) -> None:
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.zoom_by((pct / 100) / self.transform().m11())
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def fit(self) -> None:
        if self._paper is None:
            return
        self.resetTransform()
        self.fitInView(self._paper.rect().adjusted(-30, -30, 30, 30), Qt.KeepAspectRatio)
        if self.transform().m11() > 1.4:
            self.resetTransform()
            self.scale(1.4, 1.4)
            self.centerOn(self._paper.rect().center())
        self.zoomChanged.emit(round(self.transform().m11() * 100))

    def mouseDoubleClickEvent(self, e) -> None:
        item = self.itemAt(e.position().toPoint())
        if not isinstance(item, NodeItem):
            self.fit()
        super().mouseDoubleClickEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        super().mouseReleaseEvent(e)
        item = self.itemAt(e.position().toPoint())
        if isinstance(item, NodeItem):
            self.scene().clearSelection()
            item.setSelected(True)
            self.nodeSelected.emit(dict(item.cell.attrs))

    def export_png(self, path: str, scale: float = 2.0) -> None:
        if self._paper is None:
            raise ValueError("No hay ningún mapa cargado")
        r = self._paper.rect()
        img = QImage(int(r.width() * scale), int(r.height() * scale), QImage.Format_ARGB32)
        img.fill(Qt.white)
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing |
                         QPainter.SmoothPixmapTransform)
        self.scene().clearSelection()
        self._paper.setGraphicsEffect(None)
        self.scene().render(p, QRectF(0, 0, img.width(), img.height()), r)
        p.end()
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 150))
        self._paper.setGraphicsEffect(shadow)
        img.save(path)


# ---------------------------------------------------------------- geometría
def _perimeter(r: QRectF, toward: QPointF) -> QPointF:
    c = r.center()
    dx, dy = toward.x() - c.x(), toward.y() - c.y()
    if dx == 0 and dy == 0:
        return c
    hw, hh = r.width() / 2, r.height() / 2
    t = min(hw / abs(dx) if dx else math.inf, hh / abs(dy) if dy else math.inf)
    return QPointF(c.x() + dx * t, c.y() + dy * t)


def _elbow(a: QRectF, b: QRectF) -> list[QPointF]:
    ac, bc = a.center(), b.center()
    if abs(bc.y() - ac.y()) >= abs(bc.x() - ac.x()):
        down = bc.y() > ac.y()
        s = QPointF(ac.x(), a.bottom() if down else a.top())
        e = QPointF(bc.x(), b.top() if down else b.bottom())
        my = (s.y() + e.y()) / 2
        return [s, QPointF(s.x(), my), QPointF(e.x(), my), e]
    right = bc.x() > ac.x()
    s = QPointF(a.right() if right else a.left(), ac.y())
    e = QPointF(b.left() if right else b.right(), bc.y())
    mx = (s.x() + e.x()) / 2
    return [s, QPointF(mx, s.y()), QPointF(mx, e.y()), e]


def _path_len(pts: list[QPointF]) -> float:
    return sum(math.hypot(pts[i + 1].x() - pts[i].x(), pts[i + 1].y() - pts[i].y())
               for i in range(len(pts) - 1))


def _point_at(pts: list[QPointF], dist: float) -> QPointF:
    acc = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg = math.hypot(b.x() - a.x(), b.y() - a.y())
        if acc + seg >= dist and seg > 0:
            t = (dist - acc) / seg
            return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)
        acc += seg
    return pts[-1]


def _rounded_path(pts: list[QPointF], radius: float) -> QPainterPath:
    path = QPainterPath(pts[0])
    if radius <= 0 or len(pts) < 3:
        for p in pts[1:]:
            path.lineTo(p)
        return path
    for i in range(1, len(pts) - 1):
        prev, cur, nxt = pts[i - 1], pts[i], pts[i + 1]
        d1 = math.hypot(cur.x() - prev.x(), cur.y() - prev.y())
        d2 = math.hypot(nxt.x() - cur.x(), nxt.y() - cur.y())
        r = min(radius, d1 / 2, d2 / 2)
        if d1 == 0 or d2 == 0:
            continue
        p1 = QPointF(cur.x() - (cur.x() - prev.x()) * r / d1, cur.y() - (cur.y() - prev.y()) * r / d1)
        p2 = QPointF(cur.x() + (nxt.x() - cur.x()) * r / d2, cur.y() + (nxt.y() - cur.y()) * r / d2)
        path.lineTo(p1)
        path.quadTo(cur, p2)
    path.lineTo(pts[-1])
    return path
