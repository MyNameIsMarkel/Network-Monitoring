# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: genera una carpeta autocontenida (dist/NetworkMonitoring) para Windows y Linux.
#   pyinstaller packaging/netmon.spec --noconfirm
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
IS_WIN = sys.platform.startswith("win")

datas = [(str(ROOT / "netmon" / "assets"), "netmon/assets")]
datas += collect_data_files("netaddr")          # base de datos OUI (fabricantes)
datas += collect_data_files("pysnmp")
hiddenimports = collect_submodules("pysnmp") + collect_submodules("pyasn1") + [
    "netmon.ui.app", "netmon.cli", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
]

excludes = [
    "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "matplotlib", "numpy", "PIL",
]

a = Analysis(
    [str(ROOT / "netmon" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NetworkMonitoring" if IS_WIN else "netmon",
    console=False,
    icon=str(ROOT / "netmon" / "assets" / ("icon.ico" if IS_WIN else "icon.png")),
    version=str(ROOT / "packaging" / "windows" / "version_info.txt") if IS_WIN else None,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="NetworkMonitoring", upx=False)
