"""Rutas por defecto (carpeta de mapas) y localización de recursos empaquetados."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_path(*parts: str) -> Path:
    """Ruta a un recurso, tanto en desarrollo como dentro del ejecutable de PyInstaller."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass, "netmon", *parts)
    return Path(__file__).resolve().parent.joinpath(*parts)


def documents_dir() -> Path:
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL
            if buf.value:
                return Path(buf.value)
        except Exception:
            pass
        return Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
    xdg = os.environ.get("XDG_DOCUMENTS_DIR")
    if xdg:
        return Path(xdg)
    try:
        cfg = Path.home() / ".config" / "user-dirs.dirs"
        for line in cfg.read_text().splitlines():
            if line.startswith("XDG_DOCUMENTS_DIR="):
                val = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(Path.home()))
                return Path(val)
    except OSError:
        pass
    for name in ("Documents", "Documentos"):
        if (Path.home() / name).is_dir():
            return Path.home() / name
    return Path.home()


def default_output_dir() -> Path:
    return documents_dir() / "Mapas de red"
