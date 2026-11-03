"""Generador de diagramas draw.io (.drawio) a partir del resultado del escaneo.

Disposición jerárquica en árbol: Internet → puerta de enlace → núcleo → acceso → equipos.
Los equipos finales de cada switch se colocan en una cuadrícula alimentada por un "bus"
ortogonal para que cada conexión se lea con claridad.
"""
from __future__ import annotations

import html
import math
import os
import re
import uuid
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from netmon import __version__
from netmon.core.models import DEVICE_TYPES, INFRA_TYPES, MODE_ACTIVE, Device, Link, ScanResult
from netmon.drawio.icons import INK, data_uri

# ----------------------------------------------------------------- medidas
INFRA_W, INFRA_ICON = 150, 58
LEAF_W, LEAF_ICON = 120, 44
LEAF_PITCH = 132
LEAF_ROW = 128
LEAF_COLS = 6
TRUNK_PAD = 26
LEVEL_GAP = 96
BLOCK_GAP = 48
BAND = 24
MARGIN = 40
HEADER_H = 96
MUTED = "#57606A"
FAINT = "#8C959F"

EDGE_BASE = ("edgeStyle=none;rounded=1;arcSize=10;html=1;endArrow=none;startArrow=none;"
             "jumpStyle=none;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;"
             "entryDx=0;entryDy=0;")
EDGE_KIND = {
    "lldp": f"strokeColor={INK};strokeWidth=2.2;",
    "cdp": f"strokeColor={INK};strokeWidth=2.2;",
    "internet": f"strokeColor={INK};strokeWidth=2;dashed=1;dashPattern=8 5;",
    "fdb": f"strokeColor={MUTED};strokeWidth=1.3;",
    "inferred": f"strokeColor={FAINT};strokeWidth=1.2;dashed=1;dashPattern=4 4;",
}
EDGE_LEGEND = {
    "lldp": "Enlace confirmado (LLDP/CDP)",
    "fdb": "Ubicado por tabla MAC (FDB)",
    "inferred": "Conexión inferida (sin confirmar)",
    "internet": "Salida a Internet",
}


@dataclass
class _Node:
    dev: Device
    children: list["_Node"] = field(default_factory=list)
    leaves: list["_Node"] = field(default_factory=list)
    link_from_parent: Link | None = None
    width: float = 0
    x: float = 0
    y: float = 0
    cx: float = 0
    cell_w: float = 0
    icon: float = 0
    label_h: float = 0


def _esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def _label(dev: Device, leaf: bool) -> str:
    lines = [f"<b>{_esc(dev.name)}</b>"]
    sub: list[str] = []
    if dev.ip and dev.name != dev.ip:
        sub.append(dev.ip)
    if dev.dtype == "internet":
        pass
    elif leaf:
        extra = dev.vendor if dev.vendor and dev.vendor != "MAC aleatoria" else ""
        if dev.attach_port:
            extra = f"puerto {dev.attach_port}" + (f" · {extra}" if extra else "")
        if extra:
            sub.append(extra)
    else:
        if dev.model:
            sub.append(dev.model)
        elif dev.vendor:
            sub.append(dev.vendor)
    if sub:
        lines.append(f'<span style="font-size:10px;color:{MUTED};">'
                     + "<br>".join(_esc(s) for s in sub) + "</span>")
    return "<br>".join(lines)


def _label_height(dev: Device, leaf: bool, width: float) -> float:
    txt = re.sub(r"<[^>]+>", "\n", _label(dev, leaf).replace("<br>", "\n"))
    lines = 0
    chars_per_line = max(8, int(width / 6.2))
    for ln in [l for l in txt.split("\n") if l.strip()]:
        lines += max(1, math.ceil(len(html.unescape(ln)) / chars_per_line))
    return 6 + lines * 13


def _tooltip(dev: Device) -> str:
    rows = [f"{DEVICE_TYPES.get(dev.dtype, dev.dtype)}: {dev.name}"]
    if dev.all_ips():
        rows.append("IP: " + ", ".join(sorted(dev.all_ips())))
    if dev.mac:
        rows.append(f"MAC: {dev.mac}")
    if dev.vendor:
        rows.append(f"Fabricante: {dev.vendor}")
    if dev.model:
        rows.append(f"Modelo: {dev.model}")
    if dev.description and dev.description != dev.model:
        rows.append(f"Sistema: {dev.description[:140]}")
    if dev.open_ports:
        rows.append("Puertos: " + ", ".join(map(str, dev.open_ports)))
    if dev.attach_port:
        rows.append(f"Conectado en: {dev.attach_port}")
    if dev.location:
        rows.append(f"Ubicación: {dev.location}")
    rows.append("Detectado por: " + ", ".join(sorted(dev.sources)))
    return "\n".join(rows)


class DrawioBuilder:
    def __init__(self, result: ScanResult):
        self.r = result
        self.cells: list[ET.Element] = []
        self.overlay: list[ET.Element] = []
        self._id = 2
        self.cell_ids: dict[str, str] = {}
        self.nodes: dict[str, _Node] = {}
        self.bounds = [math.inf, math.inf, -math.inf, -math.inf]

    def nid(self) -> str:
        self._id += 1
        return f"n{self._id}"

    # ------------------------------------------------------------- árbol
    def _tree(self) -> list[_Node]:
        devices = self.r.devices
        adj: dict[str, list[Link]] = {d: [] for d in devices}
        for l in self.r.links:
            if l.a in adj and l.b in adj:
                adj[l.a].append(l)
                adj[l.b].append(l)
        rank = {"internet": 0, "lldp": 1, "cdp": 1, "fdb": 2, "inferred": 3}
        visited: set[str] = set()
        self.tree_links: set[int] = set()
        roots: list[_Node] = []

        def build_from(root_id: str) -> _Node:
            root = _Node(devices[root_id])
            visited.add(root_id)
            q = deque([root])
            while q:
                node = q.popleft()
                links = sorted(adj[node.dev.id], key=lambda l: (rank.get(l.kind, 4),
                                                                 self._other(l, node.dev.id)))
                for l in links:
                    other = self._other(l, node.dev.id)
                    if other in visited:
                        continue
                    visited.add(other)
                    self.tree_links.add(id(l))
                    child = _Node(devices[other], link_from_parent=l)
                    node.children.append(child)
                    q.append(child)
            return root

        order = []
        if self.r.root_id and self.r.root_id in devices:
            order.append(self.r.root_id)
        degree = {d: len(v) for d, v in adj.items()}
        order += sorted(devices, key=lambda d: (devices[d].dtype not in INFRA_TYPES, -degree[d]))
        for did in order:
            if did not in visited:
                roots.append(build_from(did))
        for root in roots:
            self._split_leaves(root)
        return roots

    @staticmethod
    def _other(l: Link, me: str) -> str:
        return l.b if l.a == me else l.a

    def _split_leaves(self, node: _Node) -> None:
        kids, leaves = [], []
        for c in node.children:
            self._split_leaves(c)
            if c.children or c.leaves or c.dev.dtype in INFRA_TYPES:
                kids.append(c)
            else:
                leaves.append(c)
        order = list(DEVICE_TYPES)
        leaves.sort(key=lambda n: (order.index(n.dev.dtype) if n.dev.dtype in order else 99,
                                   _ip_key(n.dev.ip), n.dev.name))
        kids.sort(key=lambda n: (order.index(n.dev.dtype) if n.dev.dtype in order else 99,
                                 n.dev.name))
        node.children, node.leaves = kids, leaves

    # ------------------------------------------------------------- medidas
    def _measure(self, node: _Node, leaf: bool = False) -> float:
        node.cell_w = LEAF_W if leaf else INFRA_W
        node.icon = LEAF_ICON if leaf else INFRA_ICON
        node.label_h = _label_height(node.dev, leaf, node.cell_w)
        if leaf:
            node.width = LEAF_W
            return node.width
        blocks = []
        if node.leaves:
            for l in node.leaves:
                self._measure(l, leaf=True)
            cols = min(LEAF_COLS, len(node.leaves))
            blocks.append(TRUNK_PAD + cols * LEAF_PITCH - (LEAF_PITCH - LEAF_W))
        for c in node.children:
            blocks.append(self._measure(c))
        below = sum(blocks) + BLOCK_GAP * max(0, len(blocks) - 1)
        node.width = max(node.cell_w, below)
        return node.width

    def _leaf_rows_height(self, node: _Node) -> float:
        rows = math.ceil(len(node.leaves) / LEAF_COLS)
        return rows * LEAF_ROW

    # ------------------------------------------------------------- colocación
    def _place(self, node: _Node, left: float, top: float) -> None:
        blocks_w = []
        if node.leaves:
            cols = min(LEAF_COLS, len(node.leaves))
            blocks_w.append(TRUNK_PAD + cols * LEAF_PITCH - (LEAF_PITCH - LEAF_W))
        blocks_w += [c.width for c in node.children]
        below = sum(blocks_w) + BLOCK_GAP * max(0, len(blocks_w) - 1)
        cursor = left + (node.width - below) / 2
        child_top = top + node.icon + node.label_h + LEVEL_GAP - BAND
        band_y = top + node.icon + node.label_h + 14

        node.y = top
        node.cx = left + node.width / 2
        self._vertex(node, leaf=False)

        if node.leaves:
            trunk_x = cursor + 8
            for i, leaf in enumerate(node.leaves):
                r, c = divmod(i, LEAF_COLS)
                lx = cursor + TRUNK_PAD + c * LEAF_PITCH
                ly = child_top + r * LEAF_ROW
                leaf.cx = lx + LEAF_W / 2
                leaf.y = ly
                self._vertex(leaf, leaf=True)
                bus_y = ly - 18
                pts = [(node.cx, band_y), (trunk_x, band_y), (trunk_x, bus_y), (leaf.cx, bus_y)]
                self._edge(node, leaf, leaf.link_from_parent, pts)
            cursor += blocks_w[0] + BLOCK_GAP
            blocks_w = blocks_w[1:]
        for child, w in zip(node.children, blocks_w):
            self._place(child, cursor, child_top)
            pts = [(node.cx, band_y), (child.cx, band_y)]
            self._edge(node, child, child.link_from_parent, pts, ports=True)
            cursor += w + BLOCK_GAP

    # ------------------------------------------------------------- celdas
    def _bound(self, x1, y1, x2, y2) -> None:
        b = self.bounds
        b[0], b[1], b[2], b[3] = min(b[0], x1), min(b[1], y1), max(b[2], x2), max(b[3], y2)

    def _vertex(self, node: _Node, leaf: bool) -> None:
        dev = node.dev
        cid = self.nid()
        self.cell_ids[dev.id] = cid
        self.nodes[dev.id] = node
        x = node.cx - node.cell_w / 2
        font = 11 if leaf else 12
        style = (f"shape=image;html=1;image={data_uri(dev.dtype)};imageAspect=1;aspect=fixed;"
                 f"verticalLabelPosition=bottom;verticalAlign=top;align=center;spacingTop=2;"
                 f"labelBackgroundColor=#FFFFFF;fontFamily=Helvetica;fontSize={font};"
                 f"fontColor={INK};whiteSpace=wrap;")
        attrs = {
            "id": cid, "label": _label(dev, leaf), "tooltip": _tooltip(dev),
            "nm_type": dev.dtype, "nm_type_name": DEVICE_TYPES.get(dev.dtype, dev.dtype),
            "nm_name": dev.name, "nm_ip": dev.ip, "nm_ips": ", ".join(sorted(dev.all_ips())),
            "nm_mac": dev.mac, "nm_vendor": dev.vendor, "nm_model": dev.model,
            "nm_description": dev.description[:300], "nm_ports": ",".join(map(str, dev.open_ports)),
            "nm_port": dev.attach_port, "nm_sources": ",".join(sorted(dev.sources)),
            "nm_location": dev.location,
        }
        obj = ET.Element("object", {k: v for k, v in attrs.items() if v or k in ("id", "label")})
        cell = ET.SubElement(obj, "mxCell", {"style": style, "vertex": "1", "parent": "1"})
        ET.SubElement(cell, "mxGeometry", {"x": _f(x), "y": _f(node.y), "width": _f(node.cell_w),
                                           "height": _f(node.icon), "as": "geometry"})
        self.cells.append(obj)
        self._bound(x, node.y, x + node.cell_w, node.y + node.icon + node.label_h)

    def _edge(self, parent: _Node, child: _Node, link: Link | None, pts, ports: bool = False):
        kind = link.kind if link else "inferred"
        style = EDGE_BASE + EDGE_KIND.get(kind, EDGE_KIND["inferred"])
        # eliminar puntos redundantes (colineales o repetidos)
        start = (parent.cx, parent.y + parent.icon)
        end = (child.cx, child.y)
        full = _simplify([start] + list(pts) + [end])
        eid = self.nid()
        cell = ET.Element("mxCell", {"id": eid, "value": "", "style": style, "edge": "1",
                                     "parent": "1", "source": self.cell_ids[parent.dev.id],
                                     "target": self.cell_ids[child.dev.id]})
        geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        inner = full[1:-1]
        if inner:
            arr = ET.SubElement(geo, "Array", {"as": "points"})
            for x, y in inner:
                ET.SubElement(arr, "mxPoint", {"x": _f(x), "y": _f(y)})
        self.cells.append(cell)

        if ports and link and (link.a_port or link.b_port):
            p_port = link.a_port if link.a == parent.dev.id else link.b_port
            c_port = link.b_port if link.a == parent.dev.id else link.a_port
            if link.speed and p_port:
                p_port = f"{p_port} · {link.speed}"
            total = _length(full)
            last = _dist(full[-2], full[-1])
            if p_port:
                at = total - last + 13
                if len(full) == 2:      # tramo recto: dejar libre la etiqueta del equipo padre
                    at = parent.label_h + 12
                self._edge_label(eid, p_port, total, at)
            if c_port:
                self._edge_label(eid, c_port, total, total - 13)

    def _edge_label(self, eid: str, text: str, total: float, at: float) -> None:
        rel = 0 if total <= 0 else max(-1.0, min(1.0, 2 * at / total - 1))
        cell = ET.Element("mxCell", {
            "id": self.nid(), "value": _esc(text), "vertex": "1", "connectable": "0",
            "parent": eid,
            "style": f"edgeLabel;html=1;align=center;verticalAlign=middle;resizable=0;points=[];"
                     f"fontFamily=Helvetica;fontSize=9;fontColor={MUTED};"
                     f"labelBackgroundColor=#FFFFFF;"})
        geo = ET.SubElement(cell, "mxGeometry", {"x": f"{rel:.4f}", "relative": "1",
                                                 "as": "geometry"})
        ET.SubElement(geo, "mxPoint", {"as": "offset"})
        self.cells.append(cell)

    def _extra_edges(self) -> None:
        extra = 0
        for l in self.r.links:
            if id(l) in self.tree_links or l.a not in self.cell_ids or l.b not in self.cell_ids:
                continue
            # Enlace redundante: se dibuja por el lateral derecho para no tapar el principal
            na, nb = self.nodes[l.a], self.nodes[l.b]
            lane = max(na.cx + na.cell_w / 2, nb.cx + nb.cell_w / 2) + 18 + 10 * extra
            extra += 1
            style = ("edgeStyle=none;rounded=1;arcSize=10;html=1;endArrow=none;startArrow=none;"
                     "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;"
                     + EDGE_KIND.get(l.kind, EDGE_KIND["inferred"]))
            label = " ↔ ".join(p for p in (l.a_port, l.b_port) if p)
            cell = ET.Element("mxCell", {"id": self.nid(), "value": _esc(label), "style": style +
                                         f"fontSize=9;fontColor={MUTED};labelBackgroundColor=#FFFFFF;",
                                         "edge": "1", "parent": "1",
                                         "source": self.cell_ids[l.a], "target": self.cell_ids[l.b]})
            geo = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
            arr = ET.SubElement(geo, "Array", {"as": "points"})
            for n in (na, nb):
                ET.SubElement(arr, "mxPoint", {"x": _f(lane), "y": _f(n.y + n.icon / 2)})
            self._bound(lane, na.y, lane + 4, nb.y)
            self.cells.append(cell)

    # ------------------------------------------------------------- cabecera y leyenda
    def _header(self, left: float, top: float) -> None:
        r = self.r
        n = len([d for d in r.devices.values() if d.dtype not in ("internet",)])
        mode = "Escaneo activo completo" if r.mode == MODE_ACTIVE else "Descubrimiento SNMP + LLDP/CDP"
        when = (r.finished or r.started).strftime("%d/%m/%Y %H:%M")
        scope = ", ".join(r.targets[:4]) + (" …" if len(r.targets) > 4 else "")
        sub = f"{when}  ·  {mode}  ·  {n} dispositivos  ·  {len(r.links)} conexiones"
        if scope:
            sub += f"  ·  {scope}"
        value = (f'<div style="text-align:left"><span style="font-size:22px;font-weight:600;'
                 f'letter-spacing:-0.3px">Mapa de red</span><br>'
                 f'<span style="font-size:11px;color:{MUTED}">{_esc(sub)}</span></div>')
        cell = ET.Element("mxCell", {"id": self.nid(), "value": value, "vertex": "1", "parent": "1",
                                     "style": f"text;html=1;align=left;verticalAlign=top;"
                                              f"fontFamily=Helvetica;fontColor={INK};"
                                              f"whiteSpace=nowrap;"})
        ET.SubElement(cell, "mxGeometry", {"x": _f(left), "y": _f(top), "width": "720",
                                           "height": "52", "as": "geometry"})
        self.cells.append(cell)
        line = ET.Element("mxCell", {"id": self.nid(), "value": "", "vertex": "1", "parent": "1",
                                     "style": f"shape=line;strokeColor={INK};strokeWidth=2;html=1;"})
        ET.SubElement(line, "mxGeometry", {"x": _f(left), "y": _f(top + 62), "width": "64",
                                           "height": "4", "as": "geometry"})
        self.cells.append(line)

    def _legend(self, left: float, top: float) -> None:
        types = [t for t in DEVICE_TYPES if any(d.dtype == t for d in self.r.devices.values())]
        kinds = []
        for l in self.r.links:
            k = "lldp" if l.kind == "cdp" else l.kind
            if k not in kinds:
                kinds.append(k)
        kinds.sort(key=lambda k: list(EDGE_LEGEND).index(k) if k in EDGE_LEGEND else 9)
        row = 26
        h = 48 + len(types) * row + 12 + len(kinds) * row + 10
        w = 236
        box = ET.Element("mxCell", {"id": self.nid(), "value": "", "vertex": "1", "parent": "1",
                                    "style": "rounded=1;arcSize=4;html=1;fillColor=#FAFBFC;"
                                             "strokeColor=#D0D7DE;strokeWidth=1;"})
        ET.SubElement(box, "mxGeometry", {"x": _f(left), "y": _f(top), "width": _f(w),
                                          "height": _f(h), "as": "geometry"})
        self.cells.append(box)
        self._text(left + 16, top + 12, 200, 20, "<b>LEYENDA</b>", 10, INK, spacing=True)
        y = top + 42
        for t in types:
            icon = ET.Element("mxCell", {"id": self.nid(), "value": "", "vertex": "1", "parent": "1",
                                         "style": f"shape=image;html=1;image={data_uri(t)};"
                                                  f"imageAspect=1;aspect=fixed;"})
            ET.SubElement(icon, "mxGeometry", {"x": _f(left + 16), "y": _f(y), "width": "20",
                                               "height": "20", "as": "geometry"})
            self.cells.append(icon)
            self._text(left + 46, y, 180, 20, _esc(DEVICE_TYPES[t]), 11, INK)
            y += row
        y += 12
        for k in kinds:
            style = ("html=1;endArrow=none;startArrow=none;" +
                     EDGE_KIND.get(k, EDGE_KIND["inferred"]))
            e = ET.Element("mxCell", {"id": self.nid(), "value": "", "style": style, "edge": "1",
                                      "parent": "1"})
            g = ET.SubElement(e, "mxGeometry", {"relative": "1", "as": "geometry"})
            ET.SubElement(g, "mxPoint", {"x": _f(left + 16), "y": _f(y + 10), "as": "sourcePoint"})
            ET.SubElement(g, "mxPoint", {"x": _f(left + 38), "y": _f(y + 10), "as": "targetPoint"})
            self.overlay.append(e)
            self._text(left + 46, y, 184, 20, _esc(EDGE_LEGEND.get(k, k)), 11, INK)
            y += row
        self._bound(left, top, left + w, top + h)

    def _text(self, x, y, w, h, value, size, color, spacing=False):
        cell = ET.Element("mxCell", {
            "id": self.nid(), "value": value, "vertex": "1", "parent": "1",
            "style": f"text;html=1;align=left;verticalAlign=middle;fontFamily=Helvetica;"
                     f"fontSize={size};fontColor={color};whiteSpace=nowrap;"
                     + ("spacingLeft=0;" if spacing else "")})
        ET.SubElement(cell, "mxGeometry", {"x": _f(x), "y": _f(y), "width": _f(w),
                                           "height": _f(h), "as": "geometry"})
        self.cells.append(cell)

    # ------------------------------------------------------------- salida
    def build(self) -> str:
        roots = self._tree()
        x = MARGIN
        top = MARGIN + HEADER_H
        for root in roots:
            self._measure(root)
        # Componentes grandes primero; los aislados a continuación
        for root in roots:
            self._place(root, x, top)
            x += root.width + BLOCK_GAP * 2
        self._extra_edges()
        diagram_right = self.bounds[2] if self.bounds[2] > -math.inf else MARGIN + 400
        self._legend(diagram_right + 70, top)
        self._header(MARGIN, MARGIN)
        self._bound(MARGIN, MARGIN, MARGIN + 720, MARGIN + 60)

        width = int(self.bounds[2] + MARGIN)
        height = int(self.bounds[3] + MARGIN)
        now = datetime.now().isoformat(timespec="seconds")
        mxfile = ET.Element("mxfile", {"host": "NetworkMonitoring", "modified": now,
                                       "agent": f"Network Monitoring {__version__}",
                                       "version": "24.7.17", "type": "device"})
        diagram = ET.SubElement(mxfile, "diagram", {"id": uuid.uuid4().hex[:20],
                                                    "name": "Mapa de red"})
        model = ET.SubElement(diagram, "mxGraphModel", {
            "dx": "1400", "dy": "900", "grid": "0", "gridSize": "10", "guides": "1",
            "tooltips": "1", "connect": "1", "arrows": "1", "fold": "1", "page": "1",
            "pageScale": "1", "pageWidth": str(max(width, 850)), "pageHeight": str(max(height, 600)),
            "math": "0", "shadow": "0", "background": "#FFFFFF"})
        root_el = ET.SubElement(model, "root")
        ET.SubElement(root_el, "mxCell", {"id": "0"})
        ET.SubElement(root_el, "mxCell", {"id": "1", "parent": "0"})
        # aristas primero (quedan por debajo de los iconos)
        edges = [c for c in self.cells if c.get("edge") == "1"]
        others = [c for c in self.cells if c.get("edge") != "1"]
        labels = [c for c in others if c.get("parent", "1") != "1"]
        vertices = [c for c in others if c.get("parent", "1") == "1"]
        for c in edges + vertices + labels + self.overlay:
            root_el.append(c)
        ET.indent(mxfile, space="  ")
        return ET.tostring(mxfile, encoding="unicode", xml_declaration=False)


def _f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _ip_key(ip: str):
    try:
        return tuple(int(x) for x in ip.split("."))
    except ValueError:
        return (999,)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _length(pts) -> float:
    return sum(_dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _simplify(pts):
    out = []
    for p in pts:
        p = (round(p[0], 1), round(p[1], 1))
        if out and out[-1] == p:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            if (a[0] == b[0] == p[0]) or (a[1] == b[1] == p[1]):
                out[-1] = p
                continue
        out.append(p)
    return out


def build_drawio(result: ScanResult) -> str:
    return DrawioBuilder(result).build()


def default_filename(result: ScanResult) -> str:
    stamp = (result.finished or result.started).strftime("%Y-%m-%d_%H-%M-%S")
    mode = "activo" if result.mode == MODE_ACTIVE else "snmp"
    return f"mapa-red_{stamp}_{mode}.drawio"


def save_drawio(result: ScanResult, folder: str | os.PathLike) -> Path:
    folder = Path(folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / default_filename(result)
    path.write_text(build_drawio(result), encoding="utf-8")
    return path
