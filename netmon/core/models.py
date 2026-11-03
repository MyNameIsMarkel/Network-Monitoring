"""Modelos de datos compartidos por el escáner, la topología y el generador draw.io."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Tipos de dispositivo que entiende el generador de diagramas
DEVICE_TYPES = {
    "internet": "Internet",
    "router": "Router",
    "firewall": "Firewall",
    "l3switch": "Switch L3",
    "switch": "Switch",
    "unmanaged": "Switch no gestionado",
    "ap": "Punto de acceso",
    "server": "Servidor",
    "nas": "NAS",
    "pc": "Equipo",
    "printer": "Impresora",
    "phone": "Teléfono IP",
    "mobile": "Móvil / tablet",
    "camera": "Cámara IP",
    "iot": "IoT",
    "unknown": "Desconocido",
}

# Dispositivos de infraestructura (se colocan como nodos del árbol, no como hojas)
INFRA_TYPES = {"internet", "router", "firewall", "l3switch", "switch", "unmanaged"}

MODE_ACTIVE = "active"
MODE_PASSIVE = "passive"


@dataclass
class SnmpCredentials:
    version: str = "2c"                      # "2c" o "3"
    communities: list[str] = field(default_factory=lambda: ["public"])
    username: str = ""
    auth_protocol: str = "SHA"               # none, MD5, SHA, SHA-256, SHA-512
    auth_key: str = ""
    priv_protocol: str = "AES-128"           # none, DES, AES-128, AES-256
    priv_key: str = ""
    port: int = 161
    timeout: float = 1.5
    retries: int = 1


@dataclass
class ScanConfig:
    mode: str = MODE_PASSIVE
    targets: list[str] = field(default_factory=list)      # CIDR a barrer (modo activo)
    seeds: list[str] = field(default_factory=list)        # switches/routers de partida (SNMP)
    use_gateway: bool = True
    snmp: SnmpCredentials = field(default_factory=SnmpCredentials)
    resolve_dns: bool = True
    detect_unmanaged: bool = True
    unmanaged_threshold: int = 3        # MACs en un puerto sin vecino LLDP => switch no gestionado
    crawl_depth: int = 6
    max_devices: int = 400              # máximo de equipos SNMP a consultar
    max_hosts: int = 4096               # máximo de IPs a barrer en modo activo
    ping_timeout: float = 1.0
    threads: int = 96
    port_timeout: float = 0.6
    ports: list[int] = field(default_factory=list)        # vacío = lista por defecto
    output_dir: str = ""


@dataclass
class Device:
    id: str
    ip: str = ""
    ips: set[str] = field(default_factory=set)
    mac: str = ""
    hostname: str = ""
    sysname: str = ""
    vendor: str = ""
    model: str = ""
    description: str = ""          # sysDescr / plataforma
    dtype: str = "unknown"
    open_ports: list[int] = field(default_factory=list)
    ttl: int | None = None
    sources: set[str] = field(default_factory=set)
    snmp: bool = False
    is_gateway: bool = False
    lldp_caps: set[str] = field(default_factory=set)
    cdp_caps: set[str] = field(default_factory=set)
    sys_services: int | None = None
    chassis_ids: set[str] = field(default_factory=set)
    location: str = ""
    attach_port: str = ""          # puerto del switch al que está conectado (por FDB)

    @property
    def name(self) -> str:
        n = self.hostname or self.sysname
        if n:
            return n
        if self.dtype == "internet":
            return "Internet"
        return self.ip or self.id

    def all_ips(self) -> set[str]:
        s = set(self.ips)
        if self.ip:
            s.add(self.ip)
        return s


@dataclass
class Link:
    a: str
    b: str
    a_port: str = ""
    b_port: str = ""
    kind: str = "inferred"         # lldp, cdp, fdb, inferred, internet
    speed: str = ""

    @property
    def confirmed(self) -> bool:
        return self.kind in ("lldp", "cdp")

    def key(self) -> tuple[str, str]:
        return tuple(sorted((self.a, self.b)))  # type: ignore[return-value]


@dataclass
class ScanResult:
    mode: str
    started: datetime
    finished: datetime | None = None
    targets: list[str] = field(default_factory=list)
    devices: dict[str, Device] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)
    root_id: str | None = None
    warnings: list[str] = field(default_factory=list)
