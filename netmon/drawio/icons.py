"""Iconos SVG monocromos (64×64) para cada tipo de dispositivo.

Se incrustan en el .drawio como `data:image/svg+xml,BASE64`, de modo que el diagrama se ve
igual en draw.io (web o escritorio) y en el visor integrado de la aplicación.
"""
from __future__ import annotations

import base64
from functools import lru_cache

INK = "#1F2328"      # color de los iconos
PAPER = "#FFFFFF"

_TILE = f'<rect x="3" y="3" width="58" height="58" rx="14" fill="{INK}"/>'
_TILE_OUTLINE = (f'<rect x="4.5" y="4.5" width="55" height="55" rx="13" fill="{PAPER}" '
                 f'stroke="{INK}" stroke-width="3" stroke-dasharray="6 4"/>')
_S = f'fill="none" stroke="{PAPER}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"'
_SD = f'fill="none" stroke="{INK}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"'


def _arrow(x1, y1, x2, y2, head=5.5, style=_S) -> str:
    """Flecha horizontal o vertical de (x1,y1) a (x2,y2)."""
    if y1 == y2:
        d = 1 if x2 > x1 else -1
        h = f"M{x2 - d * head},{y2 - head} L{x2},{y2} L{x2 - d * head},{y2 + head}"
    else:
        d = 1 if y2 > y1 else -1
        h = f"M{x2 - head},{y2 - d * head} L{x2},{y2} L{x2 + head},{y2 - d * head}"
    return f'<path {style} d="M{x1},{y1} L{x2},{y2} {h}"/>'


def _switch_arrows(style=_S) -> str:
    return (_arrow(17, 21, 47, 21, style=style) + _arrow(47, 29, 17, 29, style=style) +
            _arrow(17, 37, 47, 37, style=style) + _arrow(47, 45, 17, 45, style=style))


GLYPHS: dict[str, str] = {
    "router": _TILE + f'<circle cx="32" cy="32" r="19" {_S}/>' +
    _arrow(32, 27, 32, 16) + _arrow(32, 37, 32, 48) + _arrow(27, 32, 16, 32) +
    _arrow(37, 32, 48, 32),

    "switch": _TILE + _switch_arrows(),

    "l3switch": _TILE + _arrow(14, 23, 38, 23) + _arrow(38, 31, 14, 31) +
    _arrow(14, 39, 38, 39) + _arrow(38, 47, 14, 47) +
    f'<rect x="38" y="9" width="19" height="15" rx="4" fill="{PAPER}"/>'
    f'<text x="47.5" y="20.5" font-family="Helvetica,Arial,sans-serif" font-size="11" '
    f'font-weight="700" fill="{INK}" text-anchor="middle">L3</text>',

    "unmanaged": _TILE_OUTLINE + _switch_arrows(_SD),

    "firewall": _TILE + f'<rect x="15" y="17" width="34" height="30" rx="2" {_S}/>'
    f'<path {_S} d="M15,27 H49 M15,37 H49 M26,17 V27 M38,17 V27 M21,27 V37 M32,27 V37 '
    f'M43,27 V37 M26,37 V47 M38,37 V47"/>',

    "ap": _TILE + f'<path {_S} d="M18,27 Q32,14 46,27"/><path {_S} d="M23,33 Q32,24 41,33"/>'
    f'<circle cx="32" cy="39" r="3" fill="{PAPER}"/>'
    f'<rect x="17" y="45" width="30" height="6" rx="3" {_S}/>',

    "server": _TILE + "".join(
        f'<rect x="16" y="{y}" width="32" height="10" rx="2.5" {_S}/>'
        f'<circle cx="22" cy="{y + 5}" r="1.8" fill="{PAPER}"/>'
        f'<path {_S} d="M30,{y + 5} H42"/>' for y in (13, 27, 41)),

    "nas": _TILE + f'<rect x="16" y="13" width="32" height="38" rx="4" {_S}/>'
    f'<rect x="21" y="19" width="9" height="22" rx="1.5" {_S}/>'
    f'<rect x="34" y="19" width="9" height="22" rx="1.5" {_S}/>'
    f'<circle cx="25.5" cy="46" r="1.8" fill="{PAPER}"/><circle cx="38.5" cy="46" r="1.8" '
    f'fill="{PAPER}"/>',

    "pc": _TILE + f'<rect x="13" y="15" width="38" height="25" rx="3" {_S}/>'
    f'<path {_S} d="M32,40 V47 M23,48 H41"/>',

    "printer": _TILE + f'<path {_S} d="M22,24 V13 H42 V24"/>'
    f'<rect x="13" y="24" width="38" height="17" rx="3" {_S}/>'
    f'<path {_S} d="M22,36 H42 V51 H22 Z"/><circle cx="45" cy="30" r="1.8" fill="{PAPER}"/>',

    "phone": _TILE + f'<path {_S} d="M14,24 Q32,10 50,24 L46,30 L40,27 L40,22 Q32,19 24,22 '
    f'L24,27 L18,30 Z"/><rect x="18" y="33" width="28" height="17" rx="4" {_S}/>' +
    "".join(f'<circle cx="{x}" cy="{y}" r="1.7" fill="{PAPER}"/>'
            for x in (25, 32, 39) for y in (39, 45)),

    "mobile": _TILE + f'<rect x="21" y="11" width="22" height="42" rx="5" {_S}/>'
    f'<path {_S} d="M29,16 H35"/><circle cx="32" cy="47" r="2" fill="{PAPER}"/>',

    "camera": _TILE + f'<path {_S} d="M12,22 L40,18 L42,32 L14,36 Z"/>'
    f'<path {_S} d="M41,23 L51,21 L52,29 L42,30"/><path {_S} d="M26,35 L28,44 H18 V51"/>'
    f'<circle cx="19" cy="28" r="1.8" fill="{PAPER}"/>',

    "iot": _TILE + f'<rect x="21" y="21" width="22" height="22" rx="3" {_S}/>'
    f'<circle cx="32" cy="32" r="4" {_S}/>' +
    "".join(f'<path {_S} d="M{p},14 V20 M{p},44 V50 M14,{p} H20 M44,{p} H50"/>'
            for p in (26, 32, 38)),

    "unknown": _TILE + f'<path {_S} d="M24,25 Q24,16 32,16 Q40,16 40,24 Q40,29 34,31 '
    f'Q32,32 32,37"/><circle cx="32" cy="46" r="2.4" fill="{PAPER}"/>',

    "internet": f'<path d="M18,48 H47 Q58,48 58,37 Q58,27 48,26 Q47,13 34,13 Q24,13 21,22 '
    f'Q8,22 8,35 Q8,48 18,48 Z" fill="#F1F2F4" stroke="{INK}" stroke-width="3" '
    f'stroke-linejoin="round"/><path fill="none" stroke="{INK}" stroke-width="2.2" '
    f'stroke-linecap="round" d="M22,34 H44 M33,22 Q27,34 33,46 M33,22 Q39,34 33,46"/>'
    f'<circle cx="33" cy="34" r="12" fill="none" stroke="{INK}" stroke-width="2.2"/>',
}


@lru_cache(maxsize=None)
def svg(kind: str) -> str:
    body = GLYPHS.get(kind, GLYPHS["unknown"])
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">{body}</svg>'


@lru_cache(maxsize=None)
def data_uri(kind: str) -> str:
    """Formato que entiende draw.io dentro de un `style` (sin ';base64', que rompería el estilo)."""
    return "data:image/svg+xml," + base64.b64encode(svg(kind).encode()).decode()
