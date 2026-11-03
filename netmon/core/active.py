"""Descubrimiento activo: barrido ping, puertos TCP y resolución de nombres.

No necesita permisos de administrador ni drivers (Npcap): usa el `ping` del sistema y
conexiones TCP normales. Tras el barrido se lee la caché ARP para obtener las MAC, lo que
también descubre equipos que bloquean ICMP (Windows con firewall, por ejemplo).
"""
from __future__ import annotations

import re
import shutil
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from netmon.core.netinfo import IS_WINDOWS, run_quiet

DEFAULT_PORTS = [
    21, 22, 23, 25, 53, 80, 88, 135, 139, 143, 389, 443, 445, 515, 548, 554, 631, 636, 902,
    1433, 1883, 3268, 3306, 3389, 5000, 5001, 5060, 5432, 5900, 8000, 8006, 8008, 8080, 8291,
    8443, 9100, 37777, 62078,
]

_TTL_RE = re.compile(r"ttl[=:\s]+(\d+)", re.I)


def ping(ip: str, timeout: float) -> tuple[bool, int | None]:
    ms = max(200, int(timeout * 1000))
    if IS_WINDOWS:
        args = ["ping", "-n", "1", "-w", str(ms), ip]
    else:
        args = ["ping", "-c", "1", "-W", str(max(1, round(timeout))), "-n", ip]
    code, out = run_quiet(args, timeout=timeout + 3)
    m = _TTL_RE.search(out)
    # En Windows `ping` devuelve 0 incluso con "host inaccesible": exigimos TTL en la respuesta
    alive = bool(m) if IS_WINDOWS else (code == 0)
    return alive, int(m.group(1)) if m else None


def tcp_alive(ip: str, timeout: float) -> tuple[bool, int | None]:
    """Alternativa sin `ping`: un RST (conexión rechazada) también demuestra que el equipo existe."""
    for port in (445, 80, 443, 22, 3389, 139):
        try:
            with socket.create_connection((ip, port), timeout=timeout / 2):
                return True, None
        except ConnectionRefusedError:
            return True, None
        except OSError:
            continue
    return False, None


def ping_available() -> bool:
    return shutil.which("ping") is not None


def ping_sweep(ips: list[str], timeout: float, threads: int, cancel: threading.Event,
               progress: Callable[[int, int], None]) -> dict[str, int | None]:
    alive: dict[str, int | None] = {}
    done = 0
    probe = ping if ping_available() else tcp_alive
    with ThreadPoolExecutor(max_workers=max(4, threads)) as pool:
        futures = {pool.submit(probe, ip, timeout): ip for ip in ips}
        for fut in as_completed(futures):
            if cancel.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break
            done += 1
            ok, ttl = fut.result()
            if ok:
                alive[futures[fut]] = ttl
            if done % 8 == 0 or done == len(ips):
                progress(done, len(ips))
    return alive


def tcp_open(ip: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def port_scan(hosts: list[str], ports: list[int], timeout: float, threads: int,
              cancel: threading.Event, progress: Callable[[int, int], None]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {h: [] for h in hosts}
    jobs = [(h, p) for h in hosts for p in ports]
    done = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=max(8, threads * 2)) as pool:
        futures = {pool.submit(tcp_open, h, p, timeout): (h, p) for h, p in jobs}
        for fut in as_completed(futures):
            if cancel.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                break
            done += 1
            if fut.result():
                h, p = futures[fut]
                with lock:
                    result[h].append(p)
            if done % 50 == 0 or done == len(jobs):
                progress(done, len(jobs))
    for h in result:
        result[h].sort()
    return result


def reverse_dns(ips: list[str], threads: int, cancel: threading.Event) -> dict[str, str]:
    names: dict[str, str] = {}

    def lookup(ip: str) -> str:
        try:
            name = socket.gethostbyaddr(ip)[0]
            return "" if name == ip else name
        except (OSError, UnicodeError):
            return ""

    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(2.0)
    try:
        with ThreadPoolExecutor(max_workers=min(32, max(4, threads))) as pool:
            for ip, name in zip(ips, pool.map(lookup, ips)):
                if cancel.is_set():
                    break
                if name:
                    names[ip] = name
    finally:
        socket.setdefaulttimeout(old)
    return names


def short_hostname(name: str) -> str:
    """Nombre corto (sin dominio) salvo que sea una IP."""
    if not name or re.fullmatch(r"\d+(\.\d+){3}", name):
        return name
    return name.split(".")[0]
