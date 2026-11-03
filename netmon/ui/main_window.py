"""Ventana principal."""
from __future__ import annotations

import html
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from netmon import __app_name__, __version__
from netmon.core import netinfo
from netmon.core.models import (DEVICE_TYPES, MODE_ACTIVE, MODE_PASSIVE, ScanConfig,
                                SnmpCredentials)
from netmon.drawio.reader import read_drawio
from netmon.paths import default_output_dir, resource_path
from netmon.ui import theme
from netmon.ui.viewer import DiagramView
from netmon.ui.widgets import Logo, ModeCard, field_label, hint, section
from netmon.ui.worker import ScanWorker

AUTH_PROTOCOLS = ["SHA", "SHA-256", "SHA-512", "MD5", "none"]
PRIV_PROTOCOLS = ["AES-128", "AES-256", "DES", "none"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(__app_name__)
        self.setWindowIcon(QIcon(str(resource_path("assets", "icon.svg"))))
        self.resize(1440, 900)
        self.setMinimumSize(1080, 680)
        self.settings = QSettings("NetworkMonitoring", "NetworkMonitoring")
        self.worker: ScanWorker | None = None
        self.mode = MODE_PASSIVE
        self.current_path: Path | None = None
        self._scan_started = 0.0
        self.output_dir = Path(self.settings.value("output_dir", str(default_output_dir())))

        root = QWidget(objectName="root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_sidebar())
        lay.addWidget(self._build_main(), 1)
        self.setCentralWidget(root)

        self._timer = QTimer(self, interval=1000, timeout=self._tick)
        self._load_settings()
        self._detect_network()
        self._refresh_history()
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self._open_file)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self.view.fit)

    # ================================================================== barra lateral
    def _build_sidebar(self) -> QWidget:
        side = QWidget(objectName="sidebar")
        side.setFixedWidth(372)
        outer = QVBoxLayout(side)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(objectName="sideScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget(objectName="sideContent")
        content.setMaximumWidth(372)
        v = QVBoxLayout(content)
        v.setContentsMargins(22, 22, 22, 16)
        v.setSpacing(10)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        brand.addWidget(Logo(36))
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(QLabel(__app_name__, objectName="brand"))
        names.addWidget(QLabel(f"Mapeo de red a draw.io · v{__version__}", objectName="brandSub"))
        brand.addLayout(names)
        brand.addStretch()
        v.addLayout(brand)
        v.addSpacing(14)

        v.addWidget(section("Tipo de escaneo"))
        self.card_passive = ModeCard(
            "SNMP + LLDP/CDP",
            "Pregunta a switches y routers por sus vecinos y su tabla de direcciones MAC. "
            "Sin barridos: solo lecturas SNMP.", 1, "Impacto mínimo")
        self.card_active = ModeCard(
            "Escaneo completo",
            "Barre las subredes con ping y puertos TCP y luego consulta SNMP. Encuentra todo lo "
            "que responde, pero genera tráfico visible.", 4, "Impacto alto")
        self.card_passive.clicked.connect(lambda: self._set_mode(MODE_PASSIVE))
        self.card_active.clicked.connect(lambda: self._set_mode(MODE_ACTIVE))
        v.addWidget(self.card_passive)
        v.addWidget(self.card_active)
        v.addSpacing(8)

        # ---- alcance
        v.addWidget(section("Alcance"))
        self.scope_stack = QStackedWidget()
        # pasivo
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        pl.addWidget(field_label("Switches o routers de partida"))
        self.seeds_edit = QLineEdit(placeholderText="192.168.1.2, 192.168.1.3")
        pl.addWidget(self.seeds_edit)
        self.gw_check = QCheckBox("Incluir la puerta de enlace")
        self.gw_check.setChecked(True)
        pl.addWidget(self.gw_check)
        self.gw_hint = hint("")
        pl.addWidget(self.gw_hint)
        self.scope_stack.addWidget(pw)
        # activo
        aw = QWidget()
        al = QVBoxLayout(aw)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        al.addWidget(field_label("Subredes o rangos"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.targets_edit = QLineEdit(placeholderText="192.168.1.0/24, 10.0.5.10-80")
        row.addWidget(self.targets_edit, 1)
        det = QPushButton("Detectar", objectName="tool")
        det.clicked.connect(lambda: self._detect_network(force=True))
        row.addWidget(det)
        al.addLayout(row)
        al.addWidget(hint("Separa varias subredes con comas. No hace falta ejecutar como "
                          "administrador."))
        self.scope_stack.addWidget(aw)
        v.addWidget(self.scope_stack)
        v.addSpacing(8)

        # ---- SNMP
        v.addWidget(section("Credenciales SNMP"))
        seg = QFrame(objectName="segBox")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.v2_btn = QPushButton("v2c", objectName="seg", checkable=True)
        self.v3_btn = QPushButton("v3", objectName="seg", checkable=True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for b in (self.v2_btn, self.v3_btn):
            grp.addButton(b)
            sl.addWidget(b)
        self.v2_btn.setChecked(True)
        self.v2_btn.toggled.connect(self._update_snmp_fields)
        v.addWidget(seg)

        self.v2_box = QWidget()
        l2 = QVBoxLayout(self.v2_box)
        l2.setContentsMargins(0, 4, 0, 0)
        l2.setSpacing(6)
        l2.addWidget(field_label("Comunidades (se prueban en orden)"))
        self.community_edit = QLineEdit("public")
        self.community_edit.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        l2.addWidget(self.community_edit)
        v.addWidget(self.v2_box)

        self.v3_box = QWidget()
        g3 = QGridLayout(self.v3_box)
        g3.setContentsMargins(0, 4, 0, 0)
        g3.setHorizontalSpacing(8)
        g3.setVerticalSpacing(6)
        self.v3_user = QLineEdit(placeholderText="Usuario")
        self.v3_auth = QComboBox()
        self.v3_auth.addItems(AUTH_PROTOCOLS)
        self.v3_auth_key = QLineEdit(placeholderText="Clave de autenticación")
        self.v3_auth_key.setEchoMode(QLineEdit.Password)
        self.v3_priv = QComboBox()
        self.v3_priv.addItems(PRIV_PROTOCOLS)
        self.v3_priv_key = QLineEdit(placeholderText="Clave de cifrado")
        self.v3_priv_key.setEchoMode(QLineEdit.Password)
        g3.addWidget(field_label("Usuario"), 0, 0, 1, 2)
        g3.addWidget(self.v3_user, 1, 0, 1, 2)
        g3.addWidget(field_label("Autenticación"), 2, 0, 1, 2)
        g3.addWidget(self.v3_auth, 3, 0)
        g3.addWidget(self.v3_auth_key, 3, 1)
        g3.addWidget(field_label("Cifrado"), 4, 0, 1, 2)
        g3.addWidget(self.v3_priv, 5, 0)
        g3.addWidget(self.v3_priv_key, 5, 1)
        g3.setColumnStretch(1, 1)
        self.v3_auth.setFixedWidth(104)
        self.v3_priv.setFixedWidth(104)
        v.addWidget(self.v3_box)
        v.addWidget(hint("Solo lectura. Las claves no se guardan en disco."))
        v.addSpacing(6)

        # ---- avanzadas
        self.adv_btn = QPushButton("▸  Opciones avanzadas", objectName="disclosure")
        self.adv_btn.clicked.connect(self._toggle_advanced)
        v.addWidget(self.adv_btn)
        self.adv_box = QWidget()
        ga = QGridLayout(self.adv_box)
        ga.setContentsMargins(0, 0, 0, 0)
        ga.setHorizontalSpacing(10)
        ga.setVerticalSpacing(6)
        self.dns_check = QCheckBox("Resolver nombres por DNS")
        self.dns_check.setChecked(True)
        self.unmanaged_check = QCheckBox("Detectar switches no gestionados")
        self.unmanaged_check.setChecked(True)
        self.snmp_port = QSpinBox(minimum=1, maximum=65535, value=161)
        self.snmp_timeout = QDoubleSpinBox(minimum=0.3, maximum=10, value=1.5, singleStep=0.5,
                                           suffix=" s")
        self.depth_spin = QSpinBox(minimum=1, maximum=20, value=6)
        self.threads_spin = QSpinBox(minimum=4, maximum=512, value=96)
        self.maxhosts_spin = QSpinBox(minimum=16, maximum=65536, value=4096, singleStep=256)
        ga.addWidget(self.dns_check, 0, 0, 1, 2)
        ga.addWidget(self.unmanaged_check, 1, 0, 1, 2)
        for i, (lbl, w) in enumerate((("Puerto SNMP", self.snmp_port),
                                      ("Tiempo de espera SNMP", self.snmp_timeout),
                                      ("Profundidad LLDP/CDP", self.depth_spin),
                                      ("Hilos (escaneo completo)", self.threads_spin),
                                      ("Máx. direcciones a barrer", self.maxhosts_spin))):
            ga.addWidget(field_label(lbl), 2 + i, 0)
            w.setFixedWidth(104)
            ga.addWidget(w, 2 + i, 1, Qt.AlignRight)
        self.adv_box.setVisible(False)
        v.addWidget(self.adv_box)
        v.addSpacing(6)

        # ---- salida
        v.addWidget(section("Los mapas se guardan en"))
        orow = QHBoxLayout()
        orow.setSpacing(8)
        self.out_label = QLabel(objectName="path")
        self.out_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        orow.addWidget(self.out_label, 1)
        change = QPushButton("Cambiar", objectName="tool")
        change.clicked.connect(self._choose_output)
        orow.addWidget(change, 0, Qt.AlignVCenter)
        v.addLayout(orow)
        v.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(22, 12, 22, 20)
        self.scan_btn = QPushButton("Escanear red", objectName="primary")
        self.scan_btn.setCursor(Qt.PointingHandCursor)
        self.scan_btn.clicked.connect(self._start_or_cancel)
        fl.addWidget(self.scan_btn)
        outer.addWidget(foot)
        return side

    # ================================================================== zona principal
    def _build_main(self) -> QWidget:
        main = QWidget()
        v = QVBoxLayout(main)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        top = QWidget(objectName="topbar")
        top.setFixedHeight(56)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 0, 16, 0)
        tl.setSpacing(8)
        seg = QFrame(objectName="segBox")
        seg.setFixedHeight(38)
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.tab_group = QButtonGroup(self)
        self.tabs: list[QPushButton] = []
        for i, name in enumerate(("Mapa", "Dispositivos", "Registro", "Historial")):
            b = QPushButton(name, objectName="seg", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            self.tab_group.addButton(b, i)
            sl.addWidget(b)
            self.tabs.append(b)
        self.tabs[0].setChecked(True)
        self.tab_group.idClicked.connect(self._show_page)
        tl.addWidget(seg)
        tl.addSpacing(10)
        self.file_label = QLabel("", objectName="fileName")
        tl.addWidget(self.file_label, 1)
        self.btn_open = QPushButton("Abrir…", objectName="tool")
        self.btn_open.clicked.connect(self._open_file)
        self.btn_folder = QPushButton("Abrir carpeta", objectName="tool")
        self.btn_folder.clicked.connect(self._open_folder)
        self.btn_png = QPushButton("Exportar PNG", objectName="tool")
        self.btn_png.clicked.connect(self._export_png)
        self.btn_drawio = QPushButton("Editar en draw.io", objectName="tool")
        self.btn_drawio.clicked.connect(self._open_in_drawio)
        for b in (self.btn_open, self.btn_folder, self.btn_png, self.btn_drawio):
            tl.addWidget(b)
        v.addWidget(top)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_map_page())
        self.pages.addWidget(self._build_devices_page())
        self.log_view = QPlainTextEdit(objectName="log", readOnly=True)
        self.log_view.setFont(theme.mono(12))
        self.log_view.setMaximumBlockCount(5000)
        self.pages.addWidget(self.log_view)
        self.pages.addWidget(self._build_history_page())
        v.addWidget(self.pages, 1)

        status = QWidget(objectName="statusbar")
        status.setFixedHeight(34)
        stl = QHBoxLayout(status)
        stl.setContentsMargins(16, 0, 16, 0)
        stl.setSpacing(12)
        self.status_label = QLabel("Listo", objectName="status")
        stl.addWidget(self.status_label)
        self.progress = QProgressBar(textVisible=False, maximum=1000)
        self.progress.setFixedWidth(260)
        self.progress.setVisible(False)
        stl.addStretch()
        stl.addWidget(self.progress)
        self.elapsed_label = QLabel("", objectName="status")
        stl.addWidget(self.elapsed_label)
        v.addWidget(status)
        self._update_file_buttons()
        return main

    def _build_map_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        self.map_stack = QStackedWidget()

        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch()
        box = QWidget()
        box.setFixedWidth(440)
        bl = QVBoxLayout(box)
        bl.setSpacing(10)
        logo = Logo(56)
        bl.addWidget(logo, 0, Qt.AlignHCenter)
        bl.addSpacing(8)
        t = QLabel("Todavía no hay ningún mapa", objectName="emptyTitle")
        t.setAlignment(Qt.AlignCenter)
        bl.addWidget(t)
        self.empty_text = QLabel(objectName="emptyText")
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.empty_text.setWordWrap(True)
        bl.addWidget(self.empty_text)
        bl.addSpacing(6)
        ob = QPushButton("Abrir un .drawio existente", objectName="tool")
        ob.clicked.connect(self._open_file)
        bl.addWidget(ob, 0, Qt.AlignHCenter)
        el.addWidget(box, 0, Qt.AlignHCenter)
        el.addStretch()
        self.map_stack.addWidget(empty)

        self.view = DiagramView()
        self.view.set_canvas_colors(theme.CANVAS, theme.DOT)
        self.view.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{z} %"))
        self.view.nodeSelected.connect(self._show_details)
        self.map_stack.addWidget(self.view)
        grid.addWidget(self.map_stack, 0, 0)

        # control de zoom flotante
        zoom = QFrame(objectName="floating")
        zl = QHBoxLayout(zoom)
        zl.setContentsMargins(4, 4, 4, 4)
        zl.setSpacing(0)
        minus = QPushButton("−")
        minus.clicked.connect(lambda: self.view.zoom_by(1 / 1.25))
        self.zoom_label = QLabel("100 %", objectName="zoomLabel")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        plus = QPushButton("+")
        plus.clicked.connect(lambda: self.view.zoom_by(1.25))
        fit = QPushButton("Ajustar")
        fit.clicked.connect(self.view.fit)
        for w in (minus, self.zoom_label, plus, fit):
            zl.addWidget(w)
        self.zoom_box = zoom
        zoom.setParent(page)

        # panel de detalles flotante
        self.details = QFrame(objectName="floating")
        self.details.setFixedWidth(300)
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(16, 14, 12, 14)
        dl.setSpacing(4)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.d_title = QLabel(objectName="detailTitle")
        self.d_kind = QLabel(objectName="detailKind")
        titles.addWidget(self.d_title)
        titles.addWidget(self.d_kind)
        head.addLayout(titles, 1)
        close = QPushButton("✕", objectName="ghost")
        close.clicked.connect(lambda: self.details.setVisible(False))
        head.addWidget(close, 0, Qt.AlignTop)
        dl.addLayout(head)
        dl.addSpacing(6)
        self.d_grid = QGridLayout()
        self.d_grid.setHorizontalSpacing(12)
        self.d_grid.setVerticalSpacing(5)
        dl.addLayout(self.d_grid)
        self.details.setParent(page)
        self.details.setVisible(False)
        zoom.setVisible(False)
        page.installEventFilter(self)
        self._map_page = page
        return page

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "_map_page", None) and ev.type() == ev.Type.Resize:
            self._place_floating()
        return super().eventFilter(obj, ev)

    def _place_floating(self) -> None:
        page = self._map_page
        self.zoom_box.adjustSize()
        zs = self.zoom_box.sizeHint()
        self.zoom_box.setGeometry(page.width() - zs.width() - 18, page.height() - zs.height() - 18,
                                  zs.width(), zs.height())
        self.details.adjustSize()
        ds = self.details.sizeHint()
        self.details.setGeometry(18, page.height() - ds.height() - 18, 300, ds.height())
        self.zoom_box.raise_()
        self.details.raise_()

    def _build_devices_page(self) -> QWidget:
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Tipo", "Nombre", "IP", "MAC", "Fabricante",
                                              "Modelo / sistema", "Puerto", "Detectado por"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setDefaultSectionSize(34)
        h = self.table.horizontalHeader()
        h.setHighlightSections(False)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        for i, w in enumerate((130, 190, 150, 150, 170, 240, 110)):
            self.table.setColumnWidth(i, w)
        return self.table

    def _build_history_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.history = QListWidget(objectName="history")
        self.history.itemActivated.connect(lambda it: self._load_map(it.data(Qt.UserRole)))
        self.history.itemDoubleClicked.connect(lambda it: self._load_map(it.data(Qt.UserRole)))
        v.addWidget(self.history)
        return w

    # ================================================================== estado / ajustes
    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self.card_passive.setChecked(mode == MODE_PASSIVE)
        self.card_active.setChecked(mode == MODE_ACTIVE)
        self.scope_stack.setCurrentIndex(0 if mode == MODE_PASSIVE else 1)

    def _update_snmp_fields(self) -> None:
        v3 = self.v3_btn.isChecked()
        self.v2_box.setVisible(not v3)
        self.v3_box.setVisible(v3)

    def _toggle_advanced(self) -> None:
        vis = not self.adv_box.isVisible()
        self.adv_box.setVisible(vis)
        self.adv_btn.setText(("▾" if vis else "▸") + "  Opciones avanzadas")

    def _detect_network(self, force: bool = False) -> None:
        gw, _ = netinfo.default_gateway()
        self.gw_check.setEnabled(bool(gw))
        self.gw_hint.setText((f"Puerta de enlace detectada: {gw}. " if gw else
                              "No se ha detectado puerta de enlace. ") +
                             "Desde estos equipos se siguen los vecinos LLDP/CDP hasta recorrer "
                             "toda la red.")
        if force or not self.targets_edit.text().strip():
            nets = netinfo.primary_networks()
            if nets:
                self.targets_edit.setText(", ".join(nets[:2]))
            elif force:
                QMessageBox.information(self, __app_name__,
                                        "No se ha encontrado ninguna interfaz de red activa.")

    def _choose_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Carpeta para los mapas", str(self.output_dir))
        if d:
            self.output_dir = Path(d)
            self.settings.setValue("output_dir", d)
            self._update_output_label()
            self._refresh_history()

    def _update_output_label(self) -> None:
        p = str(self.output_dir)
        home = str(Path.home())
        self.out_label.setText(("~" + p[len(home):]) if p.startswith(home) else p)
        self.out_label.setToolTip(p)
        self.empty_text.setText("Elige el tipo de escaneo y pulsa «Escanear red». El diagrama se "
                                f"guardará automáticamente en {self.out_label.text()}.")

    def _load_settings(self) -> None:
        s = self.settings
        self._set_mode(s.value("mode", MODE_PASSIVE))
        self.seeds_edit.setText(s.value("seeds", ""))
        self.targets_edit.setText(s.value("targets", ""))
        self.gw_check.setChecked(s.value("use_gateway", "true") == "true")
        if s.value("snmp_version", "2c") == "3":
            self.v3_btn.setChecked(True)
        self.v3_user.setText(s.value("v3_user", ""))
        self.v3_auth.setCurrentText(s.value("v3_auth", "SHA"))
        self.v3_priv.setCurrentText(s.value("v3_priv", "AES-128"))
        self.snmp_port.setValue(int(s.value("snmp_port", 161)))
        self.dns_check.setChecked(s.value("dns", "true") == "true")
        self.unmanaged_check.setChecked(s.value("unmanaged", "true") == "true")
        self.depth_spin.setValue(int(s.value("depth", 6)))
        self.threads_spin.setValue(int(s.value("threads", 96)))
        self._update_snmp_fields()
        self._update_output_label()

    def _save_settings(self) -> None:
        s = self.settings
        s.setValue("mode", self.mode)
        s.setValue("seeds", self.seeds_edit.text())
        s.setValue("targets", self.targets_edit.text())
        s.setValue("use_gateway", "true" if self.gw_check.isChecked() else "false")
        s.setValue("snmp_version", "3" if self.v3_btn.isChecked() else "2c")
        s.setValue("v3_user", self.v3_user.text())
        s.setValue("v3_auth", self.v3_auth.currentText())
        s.setValue("v3_priv", self.v3_priv.currentText())
        s.setValue("snmp_port", self.snmp_port.value())
        s.setValue("dns", "true" if self.dns_check.isChecked() else "false")
        s.setValue("unmanaged", "true" if self.unmanaged_check.isChecked() else "false")
        s.setValue("depth", self.depth_spin.value())
        s.setValue("threads", self.threads_spin.value())

    def _config(self) -> ScanConfig:
        split = lambda t: [x.strip() for x in t.replace(";", ",").replace(" ", ",").split(",")
                           if x.strip()]
        creds = SnmpCredentials(
            version="3" if self.v3_btn.isChecked() else "2c",
            communities=split(self.community_edit.text()) or ["public"],
            username=self.v3_user.text().strip(), auth_protocol=self.v3_auth.currentText(),
            auth_key=self.v3_auth_key.text(), priv_protocol=self.v3_priv.currentText(),
            priv_key=self.v3_priv_key.text(), port=self.snmp_port.value(),
            timeout=self.snmp_timeout.value())
        return ScanConfig(mode=self.mode, targets=split(self.targets_edit.text()),
                          seeds=split(self.seeds_edit.text()), use_gateway=self.gw_check.isChecked(),
                          snmp=creds, resolve_dns=self.dns_check.isChecked(),
                          detect_unmanaged=self.unmanaged_check.isChecked(),
                          crawl_depth=self.depth_spin.value(), threads=self.threads_spin.value(),
                          max_hosts=self.maxhosts_spin.value(), output_dir=str(self.output_dir))

    # ================================================================== escaneo
    def _start_or_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.scan_btn.setEnabled(False)
            self.scan_btn.setText("Cancelando…")
            return
        cfg = self._config()
        if cfg.snmp.version == "3" and not cfg.snmp.username:
            QMessageBox.warning(self, __app_name__, "Indica el usuario SNMPv3.")
            return
        if cfg.mode == MODE_PASSIVE and not cfg.seeds and not (cfg.use_gateway and
                                                               self.gw_check.isEnabled()):
            QMessageBox.warning(self, __app_name__,
                                "Indica al menos un switch o router de partida, o activa la "
                                "puerta de enlace.")
            return
        if cfg.mode == MODE_ACTIVE:
            ips, truncated = netinfo.expand_targets(cfg.targets or netinfo.primary_networks()[:1],
                                                    cfg.max_hosts)
            if not ips:
                QMessageBox.warning(self, __app_name__, "Las subredes indicadas no son válidas. "
                                    "Usa el formato 192.168.1.0/24.")
                return
            if len(ips) > 1024:
                ok = QMessageBox.question(
                    self, __app_name__, f"Se van a barrer {len(ips)} direcciones"
                    + (" (rango recortado)" if truncated else "") + ". Puede tardar varios minutos "
                    "y generar bastante tráfico. ¿Continuar?")
                if ok != QMessageBox.Yes:
                    return
        self._save_settings()
        self.log_view.clear()
        self.worker = ScanWorker(cfg, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._on_log)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.finished.connect(self._on_thread_end)
        self._scan_started = time.monotonic()
        self._timer.start()
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.scan_btn.setText("Cancelar escaneo")
        self.scan_btn.setObjectName("danger")
        self.scan_btn.style().unpolish(self.scan_btn)
        self.scan_btn.style().polish(self.scan_btn)
        self.status_label.setText("Preparando…")
        self.worker.start()

    def _tick(self) -> None:
        s = int(time.monotonic() - self._scan_started)
        self.elapsed_label.setText(f"{s // 60}:{s % 60:02d}")

    def _on_progress(self, pct: float, phase: str) -> None:
        self.progress.setValue(int(pct * 10))
        self.status_label.setText(phase)

    def _on_log(self, level: str, msg: str) -> None:
        colors = {"warn": "#C9CDD2", "error": "#FFFFFF", "ok": "#FFFFFF", "info": theme.MUTED}
        marks = {"warn": "!", "error": "✕", "ok": "✓", "info": "·"}
        stamp = datetime.now().strftime("%H:%M:%S")
        weight = "600" if level in ("error", "ok") else "400"
        safe = html.escape(msg).replace("\n", "<br>")
        self.log_view.appendHtml(
            f'<span style="color:{theme.FAINT}">{stamp}</span>&nbsp;&nbsp;'
            f'<span style="color:{colors.get(level, theme.TEXT)};font-weight:{weight}">'
            f'{marks.get(level, "·")}&nbsp;&nbsp;{safe}</span>')

    def _on_done(self, path: str, n: int, links: int) -> None:
        self.status_label.setText(f"Mapa listo · {n} dispositivos · {links} conexiones")
        self._refresh_history()
        self._load_map(path)
        self._show_page(0)

    def _on_failed(self, msg: str) -> None:
        self.status_label.setText("El escaneo no se ha completado")
        self._on_log("error", msg)
        QMessageBox.warning(self, __app_name__, msg)

    def _on_cancelled(self) -> None:
        self.status_label.setText("Escaneo cancelado")

    def _on_thread_end(self) -> None:
        self.worker = None
        self._timer.stop()
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Escanear red")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.style().unpolish(self.scan_btn)
        self.scan_btn.style().polish(self.scan_btn)

    # ================================================================== mapas
    def _show_page(self, idx: int) -> None:
        self.tabs[idx].setChecked(True)
        self.pages.setCurrentIndex(idx)
        if idx == 3:
            self._refresh_history()

    def _load_map(self, path: str) -> None:
        try:
            self.view.load(path)
        except Exception as exc:
            QMessageBox.warning(self, __app_name__, f"No se ha podido abrir el fichero:\n{exc}")
            return
        self.current_path = Path(path)
        self.map_stack.setCurrentIndex(1)
        self.zoom_box.setVisible(True)
        self.details.setVisible(False)
        self.file_label.setText(self.current_path.name)
        self.file_label.setToolTip(str(self.current_path))
        self._fill_table()
        self._update_file_buttons()
        self._show_page(0)
        QTimer.singleShot(0, self.view.fit)
        QTimer.singleShot(0, self._place_floating)

    def _fill_table(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        page = self.view.page
        if page is None:
            return
        rows = [c.attrs for c in page.cells.values() if c.attrs.get("nm_type")
                and c.attrs.get("nm_type") != "internet"]
        order = list(DEVICE_TYPES)
        rows.sort(key=lambda a: (order.index(a["nm_type"]) if a["nm_type"] in order else 99,
                                 _ip_key(a.get("nm_ip", ""))))
        mono = theme.mono(12)
        for a in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [a.get("nm_type_name", a.get("nm_type", "")), a.get("nm_name", ""),
                    a.get("nm_ip", ""), a.get("nm_mac", ""), a.get("nm_vendor", ""),
                    a.get("nm_model") or a.get("nm_description", "")[:60], a.get("nm_port", ""),
                    a.get("nm_sources", "").replace(",", ", ")]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c in (2, 3):
                    it.setFont(mono)
                    if c == 2:
                        it.setData(Qt.UserRole, _ip_key(val))
                self.table.setItem(r, c, it)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)

    def _show_details(self, attrs: dict) -> None:
        while self.d_grid.count():
            item = self.d_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.d_title.setText(attrs.get("nm_name", ""))
        self.d_kind.setText(attrs.get("nm_type_name", ""))
        fields = [("IP", attrs.get("nm_ips") or attrs.get("nm_ip")), ("MAC", attrs.get("nm_mac")),
                  ("Fabricante", attrs.get("nm_vendor")), ("Modelo", attrs.get("nm_model")),
                  ("Puerto", attrs.get("nm_port")), ("Puertos TCP", attrs.get("nm_ports")),
                  ("Ubicación", attrs.get("nm_location")),
                  ("Origen", (attrs.get("nm_sources") or "").replace(",", ", "))]
        r = 0
        for k, val in fields:
            if not val:
                continue
            kl = QLabel(k, objectName="detailKey")
            vl = QLabel(val, objectName="detailVal")
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if k in ("IP", "MAC"):
                vl.setFont(theme.mono(12))
            self.d_grid.addWidget(kl, r, 0, Qt.AlignTop)
            self.d_grid.addWidget(vl, r, 1)
            r += 1
        self.d_grid.setColumnStretch(1, 1)
        self.details.setVisible(True)
        QTimer.singleShot(0, self._place_floating)

    def _refresh_history(self) -> None:
        self.history.clear()
        folder = self.output_dir
        files = sorted(folder.glob("*.drawio"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if folder.is_dir() else []
        if not files:
            it = QListWidgetItem("Aquí aparecerán los mapas que generes.")
            it.setFlags(Qt.NoItemFlags)
            it.setSizeHint(QSize(0, 60))
            self.history.addItem(it)
            return
        for f in files:
            st = f.stat()
            when = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y  %H:%M")
            kind = "SNMP + LLDP/CDP" if "_snmp" in f.stem else (
                "Escaneo completo" if "_activo" in f.stem else "draw.io")
            it = QListWidgetItem()
            it.setData(Qt.UserRole, str(f))
            it.setSizeHint(QSize(0, 58))
            self.history.addItem(it)
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(14, 8, 14, 8)
            col = QVBoxLayout()
            col.setSpacing(2)
            name = QLabel(f.name)
            name.setStyleSheet(f"color:{theme.TEXT}; font-size:13px;")
            meta = QLabel(f"{when}   {kind}   {st.st_size // 1024 + 1} KB")
            meta.setStyleSheet(f"color:{theme.FAINT}; font-size:12px;")
            col.addWidget(name)
            col.addWidget(meta)
            hl.addLayout(col, 1)
            self.history.setItemWidget(it, w)

    def _update_file_buttons(self) -> None:
        has = self.current_path is not None
        self.btn_png.setEnabled(has)
        self.btn_drawio.setEnabled(has)

    def _open_file(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Abrir diagrama", str(self.output_dir),
                                           "Diagramas draw.io (*.drawio *.xml)")
        if p:
            self._load_map(p)

    def _open_folder(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_dir)))

    def _export_png(self) -> None:
        if self.current_path is None:
            return
        default = str(self.current_path.with_suffix(".png"))
        p, _ = QFileDialog.getSaveFileName(self, "Exportar imagen", default, "PNG (*.png)")
        if p:
            self.view.export_png(p)
            self.status_label.setText(f"Imagen exportada: {Path(p).name}")

    def _open_in_drawio(self) -> None:
        if self.current_path is None:
            return
        exe = find_drawio()
        if exe:
            subprocess.Popen([exe, str(self.current_path)], close_fds=True)
            return
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current_path))):
            return
        QMessageBox.information(
            self, __app_name__,
            "No se ha encontrado draw.io en este equipo. Instala draw.io Desktop "
            "(github.com/jgraph/drawio-desktop) para editar el mapa sin conexión.")

    def closeEvent(self, e) -> None:
        self._save_settings()
        if self.worker is not None:
            self.worker.cancel()
            self.worker.wait(4000)
        super().closeEvent(e)


def find_drawio() -> str | None:
    cands: list[str] = []
    if sys.platform.startswith("win"):
        for env in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if base:
                cands += [os.path.join(base, "Programs", "draw.io", "draw.io.exe"),
                          os.path.join(base, "draw.io", "draw.io.exe")]
    elif sys.platform == "darwin":
        cands.append("/Applications/draw.io.app/Contents/MacOS/draw.io")
    else:
        for name in ("drawio", "draw.io"):
            w = shutil.which(name)
            if w:
                cands.append(w)
        cands += ["/opt/drawio/drawio", "/snap/bin/drawio",
                  "/var/lib/flatpak/exports/bin/com.jgraph.drawio.desktop",
                  os.path.expanduser("~/.local/share/flatpak/exports/bin/com.jgraph.drawio.desktop")]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _ip_key(ip: str):
    try:
        return tuple(int(x) for x in ip.split("."))
    except ValueError:
        return (999,)
