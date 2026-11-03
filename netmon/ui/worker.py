"""Hilo de trabajo: ejecuta el escaneo sin bloquear la interfaz y guarda el .drawio."""
from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QThread, Signal

from netmon.core.models import ScanConfig
from netmon.core.scanner import NetworkScanner, ScanCancelled
from netmon.drawio.writer import save_drawio


class ScanWorker(QThread):
    progress = Signal(float, str)
    log = Signal(str, str)
    done = Signal(str, int, int)      # ruta, dispositivos, conexiones
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, config: ScanConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            scanner = NetworkScanner(self.config, lambda p, s: self.progress.emit(p, s),
                                     lambda lvl, m: self.log.emit(lvl, m), self._cancel)
            result = scanner.run()
            path = save_drawio(result, self.config.output_dir)
            self.log.emit("ok", f"Mapa guardado en {path}")
            n = len([d for d in result.devices.values() if d.dtype != "internet"])
            self.done.emit(str(path), n, len(result.links))
        except ScanCancelled:
            self.cancelled.emit()
        except ValueError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover
            self.log.emit("error", traceback.format_exc())
            self.failed.emit(f"Error inesperado: {exc}")
