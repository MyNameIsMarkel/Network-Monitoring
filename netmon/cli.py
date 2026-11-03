"""Modo línea de comandos (sin interfaz gráfica).

Ejemplos:
    netmon --cli --mode snmp --seed 192.168.1.2 --community public
    netmon --cli --mode active --target 192.168.1.0/24
"""
from __future__ import annotations

import argparse
import sys

from netmon import __version__
from netmon.core.models import MODE_ACTIVE, MODE_PASSIVE, ScanConfig, SnmpCredentials
from netmon.core.scanner import NetworkScanner, ScanCancelled
from netmon.drawio.writer import save_drawio
from netmon.paths import default_output_dir


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="netmon --cli", description="Mapea la red y genera un .drawio")
    p.add_argument("--mode", choices=["active", "snmp"], default="snmp",
                   help="active = escaneo potente; snmp = SNMP + LLDP/CDP (impacto mínimo)")
    p.add_argument("--target", action="append", default=[], help="Subred/rango a barrer (activo)")
    p.add_argument("--seed", action="append", default=[], help="IP de switch/router semilla (SNMP)")
    p.add_argument("--no-gateway", action="store_true", help="No usar la puerta de enlace como semilla")
    p.add_argument("--community", action="append", default=[], help="Comunidad SNMP v2c")
    p.add_argument("--v3-user")
    p.add_argument("--v3-auth", default="SHA")
    p.add_argument("--v3-auth-key", default="")
    p.add_argument("--v3-priv", default="AES-128")
    p.add_argument("--v3-priv-key", default="")
    p.add_argument("--snmp-port", type=int, default=161)
    p.add_argument("--no-dns", action="store_true")
    p.add_argument("--out", default=str(default_output_dir()), help="Carpeta de salida")
    p.add_argument("--version", action="version", version=__version__)
    a = p.parse_args(argv)

    creds = SnmpCredentials(communities=a.community or ["public"], port=a.snmp_port)
    if a.v3_user:
        creds.version = "3"
        creds.username = a.v3_user
        creds.auth_protocol, creds.auth_key = a.v3_auth, a.v3_auth_key
        creds.priv_protocol, creds.priv_key = a.v3_priv, a.v3_priv_key
    cfg = ScanConfig(mode=MODE_ACTIVE if a.mode == "active" else MODE_PASSIVE,
                     targets=a.target, seeds=a.seed, use_gateway=not a.no_gateway, snmp=creds,
                     resolve_dns=not a.no_dns, output_dir=a.out)

    last = [-1]

    def progress(pct: float, phase: str) -> None:
        if int(pct) // 5 != last[0]:
            last[0] = int(pct) // 5
            print(f"  {pct:5.1f}%  {phase}", file=sys.stderr)

    def log(level: str, msg: str) -> None:
        mark = {"warn": "!", "error": "✗", "ok": "✓"}.get(level, "·")
        print(f"{mark} {msg}", file=sys.stderr)

    try:
        result = NetworkScanner(cfg, progress, log).run()
    except ScanCancelled:
        return 130
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    path = save_drawio(result, cfg.output_dir)
    print(path)
    return 0
