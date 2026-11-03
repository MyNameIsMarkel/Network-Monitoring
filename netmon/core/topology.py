"""Construcción de la topología: enlaces LLDP/CDP, ubicación de equipos por tabla MAC (FDB),
switches no gestionados y enlaces inferidos."""
from __future__ import annotations

import ipaddress

from netmon.core.models import INFRA_TYPES, Device, Link, ScanResult
from netmon.core.snmp import SnmpDeviceData

SWITCHING = {"switch", "l3switch", "router", "firewall", "unmanaged"}


def _speed_label(mbps: int) -> str:
    if mbps >= 1000:
        g = mbps / 1000
        return f"{g:g}G"
    return f"{mbps}M" if mbps else ""


class TopologyBuilder:
    def __init__(self, result: ScanResult, snmp_data: dict[str, SnmpDeviceData],
                 l3_hint: dict[str, str], detect_unmanaged: bool, unmanaged_threshold: int):
        self.r = result
        self.snmp = snmp_data
        self.l3_hint = l3_hint
        self.detect_unmanaged = detect_unmanaged
        self.threshold = max(2, unmanaged_threshold)
        self.links: dict[tuple[str, str], Link] = {}

    # ---------------------------------------------------------------- helpers
    def add_link(self, link: Link) -> None:
        if link.a == link.b or link.a not in self.r.devices or link.b not in self.r.devices:
            return
        key = link.key()
        cur = self.links.get(key)
        if cur is None:
            self.links[key] = link
            return
        rank = {"lldp": 3, "cdp": 3, "fdb": 2, "internet": 2, "inferred": 1}
        # fusionar puertos vistos desde cada extremo
        if cur.a != link.a:
            link = Link(link.b, link.a, link.b_port, link.a_port, link.kind, link.speed)
        if rank[link.kind] > rank[cur.kind]:
            link.a_port = link.a_port or cur.a_port
            link.b_port = link.b_port or cur.b_port
            self.links[key] = link
        else:
            cur.a_port = cur.a_port or link.a_port
            cur.b_port = cur.b_port or link.b_port
            cur.speed = cur.speed or link.speed

    def linked_ids(self) -> set[str]:
        s: set[str] = set()
        for l in self.links.values():
            s.add(l.a)
            s.add(l.b)
        return s

    def _owner_of_mac(self) -> dict[str, str]:
        owners: dict[str, str] = {}
        for d in self.r.devices.values():
            if d.mac:
                owners.setdefault(d.mac, d.id)
            for c in d.chassis_ids:
                if c.count(":") == 5:
                    owners.setdefault(c, d.id)
        for did, data in self.snmp.items():
            for m in data.ifmacs:
                owners.setdefault(m, did)
        return owners

    # ---------------------------------------------------------------- pasos
    def build(self, neighbor_links: list[Link]) -> None:
        for l in neighbor_links:
            self.add_link(l)
        self._speeds()
        self._place_by_fdb()
        self._attach_rest()
        self.r.links = list(self.links.values())

    def _speeds(self) -> None:
        for l in self.links.values():
            data = self.snmp.get(l.a)
            if data and l.a_port:
                for idx, name in data.ifnames.items():
                    if name == l.a_port and data.ifspeed.get(idx):
                        l.speed = _speed_label(data.ifspeed[idx])
                        break

    def _place_by_fdb(self) -> None:
        devices = self.r.devices
        owners = self._owner_of_mac()
        # puertos con vecino LLDP/CDP en cada switch: {switch: {puerto: vecino}}
        port_neighbor: dict[str, dict[str, str]] = {}
        for l in self.links.values():
            if l.kind in ("lldp", "cdp"):
                if l.a_port:
                    port_neighbor.setdefault(l.a, {})[l.a_port] = l.b
                if l.b_port:
                    port_neighbor.setdefault(l.b, {})[l.b_port] = l.a

        candidates: dict[str, list[tuple[int, str, str]]] = {}   # dev -> [(count, switch, port)]
        for sw_id, data in self.snmp.items():
            if not data.fdb:
                continue
            for mac, port in data.fdb.items():
                target = owners.get(mac)
                if target is None or target == sw_id:
                    continue
                nb = port_neighbor.get(sw_id, {}).get(port)
                count = data.port_mac_count.get(port, 1)
                if nb is not None:
                    nb_dev = devices.get(nb)
                    if nb_dev is None or nb_dev.dtype in SWITCHING or nb == target:
                        continue          # puerto troncal hacia otro switch: no sirve para ubicar
                    candidates.setdefault(target, []).append((count, nb, ""))  # detrás de AP/teléfono
                    continue
                candidates.setdefault(target, []).append((count, sw_id, port))

        already = {l.a for l in self.links.values() if l.kind in ("lldp", "cdp")} | \
                  {l.b for l in self.links.values() if l.kind in ("lldp", "cdp")}
        unmanaged: dict[tuple[str, str], str] = {}
        for dev_id, cands in candidates.items():
            dev = devices[dev_id]
            if dev_id in already:        # ya tiene un enlace confirmado por LLDP/CDP
                continue
            cands.sort()
            count, sw_id, port = cands[0]
            parent = sw_id
            if (self.detect_unmanaged and port and count >= self.threshold
                    and devices[sw_id].dtype in ("switch", "l3switch", "router", "firewall")):
                key = (sw_id, port)
                if key not in unmanaged:
                    uid = f"unmanaged:{sw_id}:{port}"
                    devices[uid] = Device(id=uid, dtype="unmanaged", sysname="Switch no gestionado",
                                          description=f"Detectado tras {devices[sw_id].name} {port}",
                                          sources={"fdb"})
                    unmanaged[key] = uid
                    self.add_link(Link(sw_id, uid, port, "", "fdb"))
                parent = unmanaged[key]
                port = ""
            dev.attach_port = port
            self.add_link(Link(parent, dev_id, port, "", "fdb"))

    def _attach_rest(self) -> None:
        devices = self.r.devices
        linked = self.linked_ids()
        root = self.r.root_id
        l3_devices = [d for d in devices.values()
                      if d.dtype in ("router", "firewall", "l3switch") and d.id in self.snmp]

        def l3_for(ip: str) -> str | None:
            try:
                addr = ipaddress.IPv4Address(ip)
            except ValueError:
                return None
            for d in l3_devices:
                for a, (_idx, mask) in self.snmp[d.id].ip_addrs.items():
                    if not mask or a.startswith("127."):
                        continue
                    try:
                        if addr in ipaddress.IPv4Network(f"{a}/{mask}", strict=False):
                            return d.id
                    except ValueError:
                        continue
            return None

        # Infraestructura suelta primero (para que cuelgue de la raíz y no de un host)
        order = sorted(devices.values(), key=lambda d: (d.dtype not in INFRA_TYPES, d.ip))
        for d in order:
            if d.id in linked or d.id == root or d.dtype == "internet":
                continue
            parent = self.l3_hint.get(d.id) or (l3_for(d.ip) if d.ip else None) or root
            if parent and parent != d.id and parent in devices:
                self.add_link(Link(parent, d.id, "", "", "inferred"))
                linked.add(d.id)
                linked.add(parent)
