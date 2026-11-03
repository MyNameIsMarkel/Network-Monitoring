"""Punto de entrada de la interfaz gráfica."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from netmon import __app_name__
from netmon.paths import resource_path


def run() -> int:
    if sys.platform.startswith("win"):
        try:  # icono propio en la barra de tareas de Windows
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NetworkMonitoring.App")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName("NetworkMonitoring")
    app.setWindowIcon(QIcon(str(resource_path("assets", "icon.svg"))))
    from netmon.ui import theme
    theme.apply(app)
    from netmon.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".drawio"):
        win._load_map(sys.argv[1])
    return app.exec()
