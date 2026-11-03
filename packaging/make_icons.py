"""Genera icon.png / icon.ico a partir de netmon/assets/icon.svg (requiere PySide6 y Pillow)."""
import io
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "netmon" / "assets" / "icon.svg"


def render(size: int) -> Image.Image:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(str(SVG)).render(p, QRectF(0, 0, size, size))
    p.end()
    buf = img.bits().tobytes() if hasattr(img.bits(), "tobytes") else bytes(img.bits())
    return Image.frombuffer("RGBA", (size, size), buf, "raw", "BGRA", 0, 1)


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    out = ROOT / "netmon" / "assets"
    render(256).save(out / "icon.png")
    render(256).save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                             (128, 128), (256, 256)])
    print("icon.png / icon.ico generados")
