"""Información de la red local: interfaces, puerta de enlace y caché ARP (Windows y Linux)."""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass

import psutil

IS_WINDOWS = sys.platform.startswith("win")

_MAC_RE = re.compile(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

_SKIP_IFACE = ("docker", "veth", "br-", "virbr", "vmnet", "vboxnet", "lo", "loopback",
               "tailscale", "zt", "wg", "tun", "tap", "isatap", "teredo")


def run_quiet(args: list[str], timeout: float = 10.0) -> tuple[int, str]:
    """Ejecuta un comando sin abrir ventanas de consola (importante en la app .exe de Windows)."""
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                  timeout=timeout)
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
    try:
        proc = subprocess.run(args, **kwargs)  # type: ignore[arg-type]
        out = proc.stdout.decode(_console_encoding(), errors="replace")
        return proc.returncode, out
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return -1, ""


def _console_encoding() -> str:
    if IS_WINDOWS:
        try:
            import ctypes
            return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        except Exception:
            return "cp850"
    return "utf-8"


def normalize_mac(mac: str) -> str:
    hexchars = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(hexchars) != 12:
        return ""
    return ":".join(hexchars[i:i + 2] for i in range(0, 12, 2)).lower()


@dataclass
class LocalInterface:
    name: str
    ip: str
    netmask: str
    mac: str

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(f"{self.ip}/{self.netmask}", strict=False)


def local_interfaces() -> list[LocalInterface]:
    result: list[LocalInterface] = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        st = stats.get(name)
        if st is not None and not st.isup:
            continue
        lname = name.lower()
        if any(lname.startswith(p) for p in _SKIP_IFACE):
            continue
        mac = ""
        for a in addrs:
            if a.family == psutil.AF_LINK:
                mac = normalize_mac(a.address or "")
        for a in addrs:
            if a.family == socket.AF_INET and a.address and a.netmask:
                ip = ipaddress.IPv4Address(a.address)
                if ip.is_loopback or ip.is_link_local:
                    continue
                result.append(LocalInterface(name, a.address, a.netmask, mac))
    return result


def default_gateway() -> tuple[str | None, str | None]:
    """Devuelve (ip_puerta_enlace, ip_local_de_salida)."""
    gw: str | None = None
    if IS_WINDOWS:
        code, out = run_quiet(["route", "print", "-4"])
        best_metric = 1 << 30
        local = None
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                try:
                    metric = int(parts[4])
                except ValueError:
                    metric = 9999
                if _IP_RE.fullmatch(parts[2]) and metric < best_metric:
                    best_metric, gw, local = metric, parts[2], parts[3]
        return gw, local or _outbound_ip()
    try:
        with open("/proc/net/route") as fh:
            for line in fh.readlines()[1:]:
                f = line.split()
                if len(f) > 3 and f[1] == "00000000" and int(f[3], 16) & 2:
                    gw = socket.inet_ntoa(bytes.fromhex(f[2])[::-1])
                    break
    except OSError:
        code, out = run_quiet(["netstat", "-rn"])
        for line in out.splitlines():
            p = line.split()
            if len(p) > 1 and p[0] in ("default", "0.0.0.0") and _IP_RE.fullmatch(p[1]):
                gw = p[1]
                break
    return gw, _outbound_ip()


def _outbound_ip() -> str | None:
    """IP local usada para salir a Internet (no envía tráfico: UDP sin datos)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def primary_networks() -> list[str]:
    """Subredes sugeridas por defecto (la de la interfaz de salida primero)."""
    gw, local_ip = default_gateway()
    nets: list[str] = []
    for itf in local_interfaces():
        net = itf.network
        if net.prefixlen < 16:  # demasiado grande para barrer por defecto
            net = ipaddress.IPv4Network(f"{itf.ip}/24", strict=False)
        cidr = str(net)
        if itf.ip == local_ip or (gw and ipaddress.IPv4Address(gw) in net):
            nets.insert(0, cidr)
        elif cidr not in nets:
            nets.append(cidr)
    seen: list[str] = []
    for n in nets:
        if n not in seen:
            seen.append(n)
    return seen


def arp_table() -> dict[str, str]:
    """Caché ARP del propio equipo (lectura local, no genera tráfico). IP -> MAC."""
    table: dict[str, str] = {}
    if not IS_WINDOWS and os.path.exists("/proc/net/arp"):
        try:
            with open("/proc/net/arp") as fh:
                for line in fh.readlines()[1:]:
                    f = line.split()
                    if len(f) >= 4 and f[2] != "0x0":
                        mac = normalize_mac(f[3])
                        if mac and mac != "00:00:00:00:00:00":
                            table[f[0]] = mac
            return table
        except OSError:
            pass
    code, out = run_quiet(["arp", "-a"] if IS_WINDOWS else ["arp", "-an"])
    for line in out.splitlines():
        ipm = _IP_RE.search(line)
        macm = _MAC_RE.search(line)
        if ipm and macm:
            mac = normalize_mac(macm.group(0))
            if mac and mac not in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00") \
                    and not mac.startswith("01:00:5e"):
                table[ipm.group(1)] = mac
    return table


def expand_targets(targets: list[str], limit: int) -> tuple[list[str], bool]:
    """Convierte CIDR/rangos/IPs sueltas en lista de IPs. Devuelve (ips, truncado)."""
    ips: list[str] = []
    seen: set[str] = set()
    truncated = False
    for raw in targets:
        t = raw.strip()
        if not t:
            continue
        hosts: list[str] = []
        try:
            if "-" in t and "/" not in t:           # 192.168.1.10-50 o 192.168.1.10-192.168.1.50
                start, end = t.split("-", 1)
                a = ipaddress.IPv4Address(start.strip())
                end = end.strip()
                b = ipaddress.IPv4Address(end if "." in end else
                                          ".".join(start.strip().split(".")[:3] + [end]))
                hosts = [str(ipaddress.IPv4Address(i)) for i in range(int(a), int(b) + 1)]
            elif "/" in t:
                net = ipaddress.IPv4Network(t, strict=False)
                hosts = [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]
            else:
                hosts = [str(ipaddress.IPv4Address(t))]
        except ValueError:
            continue
        for h in hosts:
            if h not in seen:
                if len(ips) >= limit:
                    truncated = True
                    break
                seen.add(h)
                ips.append(h)
    return ips, truncated
