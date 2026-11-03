"""Lector de ficheros .drawio (incluidos los comprimidos que guarda draw.io)."""
from __future__ import annotations

import base64
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Geometry:
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    relative: bool = False
    points: list[tuple[float, float]] = field(default_factory=list)
    source_point: tuple[float, float] | None = None
    target_point: tuple[float, float] | None = None
    offset: tuple[float, float] = (0.0, 0.0)


@dataclass
class Cell:
    id: str
    parent: str | None = None
    value: str = ""
    style: dict[str, str] = field(default_factory=dict)
    style_name: str = ""
    vertex: bool = False
    edge: bool = False
    source: str | None = None
    target: str | None = None
    geometry: Geometry = field(default_factory=Geometry)
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def is_html(self) -> bool:
        return self.style.get("html") == "1"

    def get(self, key: str, default: str = "") -> str:
        return self.style.get(key, default)

    def num(self, key: str, default: float) -> float:
        try:
            return float(self.style.get(key, default))
        except ValueError:
            return default


@dataclass
class Page:
    name: str
    cells: dict[str, Cell]
    order: list[str]
    background: str = "#FFFFFF"


def parse_style(style: str) -> tuple[str, dict[str, str]]:
    name = ""
    out: dict[str, str] = {}
    for part in (style or "").split(";"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            name = name or part.strip()
            out.setdefault(part.strip(), "1")
    return name, out


def _decompress(text: str) -> ET.Element:
    raw = base64.b64decode(text)
    try:
        data = zlib.decompress(raw, -15)
    except zlib.error:
        data = zlib.decompress(raw)
    xml = urllib.parse.unquote(data.decode("utf-8"))
    return ET.fromstring(xml)


def _geometry(el: ET.Element | None) -> Geometry:
    g = Geometry()
    if el is None:
        return g
    f = lambda k: float(el.get(k, 0) or 0)
    g.x, g.y, g.width, g.height = f("x"), f("y"), f("width"), f("height")
    g.relative = el.get("relative") == "1"
    for child in el:
        if child.tag == "Array" and child.get("as") == "points":
            g.points = [(float(p.get("x", 0)), float(p.get("y", 0))) for p in child
                        if p.tag == "mxPoint"]
        elif child.tag == "mxPoint":
            pt = (float(child.get("x", 0)), float(child.get("y", 0)))
            role = child.get("as")
            if role == "sourcePoint":
                g.source_point = pt
            elif role == "targetPoint":
                g.target_point = pt
            elif role == "offset":
                g.offset = pt
    return g


def _parse_model(model: ET.Element, name: str) -> Page:
    cells: dict[str, Cell] = {}
    order: list[str] = []
    root = model.find("root")
    if root is None:
        return Page(name, cells, order)
    for el in root:
        attrs: dict[str, str] = {}
        cell_el = el
        if el.tag in ("object", "UserObject"):
            attrs = {k: v for k, v in el.attrib.items()}
            cell_el = el.find("mxCell")
            if cell_el is None:
                continue
        elif el.tag != "mxCell":
            continue
        cid = el.get("id") or cell_el.get("id") or f"_{len(order)}"
        style_name, style = parse_style(cell_el.get("style", ""))
        value = attrs.get("label", cell_el.get("value", "")) if attrs else cell_el.get("value", "")
        c = Cell(id=cid, parent=cell_el.get("parent"), value=value or "", style=style,
                 style_name=style_name, vertex=cell_el.get("vertex") == "1",
                 edge=cell_el.get("edge") == "1", source=cell_el.get("source"),
                 target=cell_el.get("target"), geometry=_geometry(cell_el.find("mxGeometry")),
                 attrs=attrs)
        cells[cid] = c
        order.append(cid)
    return Page(name, cells, order, model.get("background", "#FFFFFF") or "#FFFFFF")


def read_drawio(path: str | Path) -> list[Page]:
    tree = ET.parse(str(path))
    root = tree.getroot()
    pages: list[Page] = []
    if root.tag == "mxGraphModel":
        return [_parse_model(root, "Página 1")]
    for i, diagram in enumerate(root.findall("diagram")):
        name = diagram.get("name", f"Página {i + 1}")
        model = diagram.find("mxGraphModel")
        if model is None and (diagram.text or "").strip():
            model = _decompress(diagram.text.strip())
        if model is not None:
            pages.append(_parse_model(model, name))
    return pages


def absolute_origin(page: Page, cell: Cell) -> tuple[float, float]:
    """Origen absoluto de un vértice (suma la posición de grupos/contenedores padre)."""
    x, y = cell.geometry.x, cell.geometry.y
    parent = page.cells.get(cell.parent or "")
    guard = 0
    while parent is not None and parent.vertex and not parent.geometry.relative and guard < 50:
        x += parent.geometry.x
        y += parent.geometry.y
        parent = page.cells.get(parent.parent or "")
        guard += 1
    return x, y
