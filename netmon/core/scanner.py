"""Orquestador del escaneo: une descubrimiento activo, SNMP/LLDP/CDP y topología."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import threading
from datetime import datetime
from typing import Callable

from netmon.core import active, netinfo
from netmon.core.classify import classify, model_from_descr, vendor_for_mac
from netmon.core.models import (MODE_ACTIVE, Device, Link, ScanConfig, ScanResult)
from netmon.core.snmp import SnmpClient, SnmpDeviceData
from netmon.core.topology import TopologyBuilder

ProgressFn = Callable[[float, str], None]
LogFn = Callable[[str, str], None]


class ScanCancelled(Exception):
    pass


def _norm_name(name: str) -> str:
    n = re.sub(r"\(.*?\)", "", name or "").strip().lower()   # CDP: "SW1(FOC1234)"
    return n.split(".")[0] if not re.fullmatch(r"\d+(\.\d+){3}", n) else n


class NetworkScanner:
    def __init__(self, config: ScanConfig, progress: ProgressFn | None = None,
                 log: LogFn | None = None, cancel: threading.Event | None = None):
        self.cfg = config
        self._progress = progress or (lambda p, s: None)
        self._log = log or (lambda lvl, m: None)
        self.cancel = cancel or threading.Event()
        self.result = ScanResult(mode=config.mode, started=datetime.now())
        self.by_ip: dict[str, str] = {}
        self.by_name: dict[str, str] = {}
        self.by_chassis: dict[str, str] = {}
        self.snmp_data: dict[str, SnmpDeviceData] = {}
        self.neighbor_links: list[Link] = []
        self.l3_hint: dict[str, str] = {}
        self.gateway_ip: str | None = None

    # ---------------------------------------------------------------- utilidades
    def log(self, msg: str, level: str = "info") -> None:
        self._log(level, msg)

    def progress(self, pct: float, phase: str) -> None:
        self._progress(max(0.0, min(100.0, pct)), phase)

    def check(self) -> None:
        if self.cancel.is_set():
            raise ScanCancelled()

    @property
    def devices(self) -> dict[str, Device]:
        return self.result.devices

    def device_for_ip(self, ip: str, create: bool = True) -> Device | None:
        did = self.by_ip.get(ip)
        if did and did in self.devices:
            return self.devices[did]
        if not create:
            return None
        dev = Device(id=f"ip:{ip}", ip=ip, ips={ip})
        self.devices[dev.id] = dev
        self.by_ip[ip] = dev.id
        return dev

    def register_ip(self, dev: Device, ip: str) -> None:
        if not ip or ip.startswith("127.") and not self._loopback_allowed():
            return
        other = self.by_ip.get(ip)
        if other and other != dev.id and other in self.devices:
            self.merge(dev, self.devices[other])
        self.by_ip[ip] = dev.id
        dev.ips.add(ip)
        if not dev.ip:
            dev.ip = ip

    def _loopback_allowed(self) -> bool:
        return any(t.startswith("127.") for t in self.cfg.targets + self.cfg.seeds)

    def merge(self, keep: Device, drop: Device) -> None:
        """Fusiona `drop` en `keep` (mismo equipo visto por varias vías)."""
        if keep.id == drop.id:
            return
        keep.ips |= drop.all_ips()
        keep.mac = keep.mac or drop.mac
        keep.hostname = keep.hostname or drop.hostname
        keep.vendor = keep.vendor or drop.vendor
        keep.open_ports = sorted(set(keep.open_ports) | set(drop.open_ports))
        keep.ttl = keep.ttl or drop.ttl
        keep.sources |= drop.sources
        keep.is_gateway = keep.is_gateway or drop.is_gateway
        keep.lldp_caps |= drop.lldp_caps
        keep.cdp_caps |= drop.cdp_caps
        keep.chassis_ids |= drop.chassis_ids
        keep.description = keep.description or drop.description
        keep.model = keep.model or drop.model
        keep.sysname = keep.sysname or drop.sysname
        for table in (self.by_ip, self.by_name, self.by_chassis):
            for k, v in list(table.items()):
                if v == drop.id:
                    table[k] = keep.id
        for l in self.neighbor_links:
            if l.a == drop.id:
                l.a = keep.id
            if l.b == drop.id:
                l.b = keep.id
        for k, v in list(self.l3_hint.items()):
            if v == drop.id:
                self.l3_hint[k] = keep.id
        if drop.id in self.l3_hint:
            self.l3_hint.setdefault(keep.id, self.l3_hint.pop(drop.id))
        if drop.id in self.snmp_data and keep.id not in self.snmp_data:
            self.snmp_data[keep.id] = self.snmp_data.pop(drop.id)
        self.devices.pop(drop.id, None)

    def find_device(self, ip: str = "", name: str = "", chassis: str = "") -> Device | None:
        for key, table in ((ip, self.by_ip), (chassis, self.by_chassis),
                           (_norm_name(name), self.by_name)):
            if key and key in table and table[key] in self.devices:
                return self.devices[table[key]]
        return None

    # ---------------------------------------------------------------- ejecución
    def run(self) -> ScanResult:
        cfg = self.cfg
        self.log(f"Inicio del escaneo · modo {'ACTIVO' if cfg.mode == MODE_ACTIVE else 'SNMP + LLDP/CDP'}")
        gw, local_ip = netinfo.default_gateway()
        self.gateway_ip = gw if cfg.use_gateway else None
        if gw:
            self.log(f"Puerta de enlace detectada: {gw}")
        try:
            if cfg.mode == MODE_ACTIVE:
                self._run_active()
            else:
                self._run_passive()
            self.check()
            self.progress(94, "Construyendo topología")
            self._finalize()
        except ScanCancelled:
            self.log("Escaneo cancelado por el usuario", "warn")
            raise
        self.result.finished = datetime.now()
        n = len([d for d in self.devices.values() if d.dtype != "internet"])
        self.log(f"Escaneo completado: {n} dispositivos, {len(self.result.links)} enlaces "
                 f"({(self.result.finished - self.result.started).seconds} s)", "ok")
        self.progress(100, "Completado")
        return self.result

    # ---------------------------------------------------------------- modo activo
    def _run_active(self) -> None:
        cfg = self.cfg
        targets = cfg.targets or netinfo.primary_networks()[:1]
        self.result.targets = targets
        ips, truncated = netinfo.expand_targets(targets, cfg.max_hosts)
        if truncated:
            w = f"Rango demasiado grande: se limitan a {cfg.max_hosts} direcciones"
            self.result.warnings.append(w)
            self.log(w, "warn")
        if not ips:
            raise ValueError("No hay direcciones válidas que escanear")
        self.log(f"Barrido de {len(ips)} direcciones en {', '.join(targets)}")
        if not active.ping_available():
            self.log("No se encuentra el comando ping: se comprueba cada equipo por TCP", "warn")
        self.progress(1, "Barrido ping")
        alive = active.ping_sweep(ips, cfg.ping_timeout, cfg.threads, self.cancel,
                                  lambda d, t: self.progress(2 + 38 * d / t, f"Barrido ping {d}/{t}"))
        self.check()
        target_set = set(ips)
        arp = {ip: mac for ip, mac in netinfo.arp_table().items() if ip in target_set}
        extra = [ip for ip in arp if ip not in alive]
        if extra:
            self.log(f"{len(extra)} equipos más encontrados por ARP (no responden a ping)")
        for ip in extra:
            alive[ip] = None
        self._add_local_interfaces(target_set)
        for ip, ttl in alive.items():
            dev = self.device_for_ip(ip)
            dev.ttl = ttl
            dev.sources.add("ping" if ttl is not None else "arp")
            if ip in arp:
                dev.mac = arp[ip]
        self.log(f"{len(alive)} equipos activos")
        hosts = sorted(alive, key=lambda x: ipaddress.IPv4Address(x))

        ports = cfg.ports or active.DEFAULT_PORTS
        self.progress(40, "Escaneo de puertos")
        self.log(f"Escaneando {len(ports)} puertos TCP en {len(hosts)} equipos")
        open_ports = active.port_scan(hosts, ports, cfg.port_timeout, cfg.threads, self.cancel,
                                      lambda d, t: self.progress(40 + 28 * d / t,
                                                                 "Escaneo de puertos"))
        self.check()
        for ip, plist in open_ports.items():
            self.devices[self.by_ip[ip]].open_ports = plist

        if cfg.resolve_dns:
            self.progress(68, "Resolviendo nombres")
            names = active.reverse_dns(hosts, cfg.threads, self.cancel)
            for ip, name in names.items():
                self.devices[self.by_ip[ip]].hostname = active.short_hostname(name)
            self.log(f"{len(names)} nombres resueltos por DNS")
        self.check()

        # SNMP sobre los equipos encontrados (enriquecimiento + topología real si hay LLDP/CDP)
        self.progress(72, "Consultando SNMP")
        seeds = list(dict.fromkeys(hosts + cfg.seeds))
        self.log(f"Probando SNMP {self._snmp_label()} en {len(seeds)} equipos")
        asyncio.run(self._snmp_crawl(seeds, quick_probe=True, base_pct=72, span=20))

    def _add_local_interfaces(self, target_set: set[str]) -> None:
        for itf in netinfo.local_interfaces():
            if itf.ip in target_set:
                dev = self.device_for_ip(itf.ip)
                dev.mac = dev.mac or itf.mac
                dev.sources.add("local")
                import socket
                dev.hostname = dev.hostname or active.short_hostname(socket.gethostname())
                dev.ttl = dev.ttl or (128 if netinfo.IS_WINDOWS else 64)

    # ---------------------------------------------------------------- modo pasivo
    def _run_passive(self) -> None:
        cfg = self.cfg
        seeds = list(dict.fromkeys(([self.gateway_ip] if self.gateway_ip else []) +
                                   [s.strip() for s in cfg.seeds if s.strip()]))
        self.result.targets = seeds
        if not seeds:
            raise ValueError("No hay equipos semilla: indica la IP de un switch o router con SNMP")
        self.progress(2, "Leyendo caché ARP local")
        arp = netinfo.arp_table()
        self.log(f"Caché ARP local: {len(arp)} entradas (lectura local, sin tráfico)")
        for ip, mac in arp.items():
            dev = self.device_for_ip(ip)
            dev.mac = mac
            dev.sources.add("arp")
        self.log(f"Descubrimiento SNMP {self._snmp_label()} desde: {', '.join(seeds)}")
        asyncio.run(self._snmp_crawl(seeds, quick_probe=False, base_pct=5, span=80))
        self.check()
        if cfg.resolve_dns:
            hosts = [d.ip for d in self.devices.values() if d.ip and not d.hostname and not d.snmp]
            if hosts:
                self.progress(88, "Resolviendo nombres (DNS)")
                names = active.reverse_dns(hosts, cfg.threads, self.cancel)
                for ip, name in names.items():
                    if ip in self.by_ip:
                        self.devices[self.by_ip[ip]].hostname = active.short_hostname(name)
                self.log(f"{len(names)} nombres resueltos por DNS")

    def _snmp_label(self) -> str:
        return "v3" if self.cfg.snmp.version == "3" else "v2c"

    # ---------------------------------------------------------------- SNMP
    async def _snmp_crawl(self, seeds: list[str], quick_probe: bool, base_pct: float,
                          span: float) -> None:
        client = SnmpClient(self.cfg.snmp)
        visited: set[str] = set()
        responders: list[str] = []
        sem = asyncio.Semaphore(48 if quick_probe else 16)
        frontier = [s for s in seeds if s]
        depth = 0
        max_depth = 1 if quick_probe else self.cfg.crawl_depth

        async def probe(ip: str) -> tuple[str, bool]:
            async with sem:
                if self.cancel.is_set():
                    return ip, False
                ok = await client.probe(ip, timeout=1.0 if quick_probe else None,
                                        retries=0 if quick_probe else None)
                return ip, ok

        async def collect(ip: str) -> SnmpDeviceData | None:
            async with sem:
                if self.cancel.is_set():
                    return None
                try:
                    return await client.collect(ip)
                except Exception as exc:  # pragma: no cover
                    self.log(f"SNMP {ip}: error al leer ({exc})", "warn")
                    return None

        try:
            while frontier and depth <= max_depth and len(responders) < self.cfg.max_devices:
                self.check()
                batch = [ip for ip in frontier if ip not in visited]
                visited.update(batch)
                if not batch:
                    break
                pct = base_pct + span * min(0.9, depth / max(1, max_depth + 1))
                self.progress(pct, f"SNMP · nivel {depth + 1} · {len(batch)} equipos")
                results = await asyncio.gather(*(probe(ip) for ip in batch))
                ok_ips = [ip for ip, ok in results if ok]
                responders.extend(ok_ips)
                if not quick_probe:
                    for ip, ok in results:
                        if not ok:
                            self.log(f"{ip} no responde a SNMP", "warn")
                datas = await asyncio.gather(*(collect(ip) for ip in ok_ips))
                next_frontier: list[str] = []
                for data in datas:
                    if data is None:
                        continue
                    new_ips = self._integrate_snmp(data)
                    next_frontier.extend(new_ips)
                depth += 1
                frontier = [ip for ip in dict.fromkeys(next_frontier) if ip not in visited]
            # Tablas MAC de los switches para ubicar los equipos finales
            switches = [did for did, d in self.snmp_data.items()
                        if self._looks_like_switch(self.devices.get(did))]
            if switches:
                self.progress(base_pct + span * 0.92, "Leyendo tablas MAC (FDB)")
                self.log(f"Leyendo tablas MAC de {len(switches)} switches")

                async def fdb(did: str) -> None:
                    async with sem:
                        await client.collect_fdb(self.snmp_data[did].ip, self.snmp_data[did])

                await asyncio.gather(*(fdb(did) for did in switches))
                total = sum(len(self.snmp_data[d].fdb) for d in switches)
                self.log(f"{total} entradas MAC leídas")
        finally:
            client.close()
        if responders:
            self.log(f"{len(responders)} equipos respondieron a SNMP", "ok")
        elif quick_probe:
            self.log("Ningún equipo respondió a SNMP: el mapa mostrará una topología lógica "
                     "(todos los equipos cuelgan de la puerta de enlace)", "warn")
        else:
            self.log("Ningún equipo respondió a SNMP. Revisa la comunidad/credenciales y que "
                     "SNMP esté habilitado en los switches", "error")

    def _looks_like_switch(self, dev: Device | None) -> bool:
        if dev is None:
            return False
        dev.dtype = classify(dev)
        if dev.dtype in ("router", "firewall"):
            return False
        return dev.dtype in ("switch", "l3switch") or "bridge" in dev.lldp_caps | dev.cdp_caps \
            or (dev.sys_services is not None and bool(dev.sys_services & 0x02))

    def _integrate_snmp(self, data: SnmpDeviceData) -> list[str]:
        """Añade la información SNMP al modelo. Devuelve IPs de vecinos para seguir explorando."""
        dev = self.find_device(ip=data.ip, name=data.sysname, chassis=data.lldp_chassis) \
            or self.device_for_ip(data.ip)
        # Si el nombre coincide con otro equipo ya creado por IP, fusionar
        by_ip = self.device_for_ip(data.ip, create=False)
        if by_ip and by_ip.id != dev.id:
            self.merge(dev, by_ip)
        dev.snmp = True
        dev.sources.add("snmp")
        dev.sysname = active.short_hostname(data.sysname) or dev.sysname
        dev.description = data.sysdescr or dev.description
        dev.model = model_from_descr(data.sysdescr) or dev.model
        dev.sys_services = data.sysservices
        dev.location = data.syslocation
        self.register_ip(dev, data.ip)
        for a in data.ip_addrs:
            if not a.startswith("127.") and not a.startswith("0."):
                self.register_ip(dev, a)
        if data.lldp_chassis:
            dev.chassis_ids.add(data.lldp_chassis)
            self.by_chassis[data.lldp_chassis] = dev.id
        if dev.sysname:
            self.by_name[_norm_name(dev.sysname)] = dev.id
        if self.gateway_ip and self.gateway_ip in dev.all_ips():
            dev.is_gateway = True
        self.snmp_data[dev.id] = data
        if not dev.mac and data.ifmacs:
            dev.mac = sorted(data.ifmacs)[0]
        if dev.mac and not dev.vendor:
            dev.vendor = vendor_for_mac(dev.mac)
        self.log(f"SNMP {data.ip}: {dev.sysname or '¿sin nombre?'} · "
                 f"{len(data.lldp_neighbors)} vecinos LLDP · {len(data.cdp_neighbors)} CDP · "
                 f"{len(data.arp)} ARP")

        next_ips: list[str] = []
        for n in data.lldp_neighbors:
            nb = self.find_device(ip=n.mgmt_ip, name=n.sysname, chassis=n.chassis_id)
            if nb is None:
                nid = f"lldp:{_norm_name(n.sysname) or n.chassis_id or n.mgmt_ip}"
                nb = self.devices.get(nid) or Device(id=nid)
                self.devices[nid] = nb
            nb.sources.add("lldp")
            nb.sysname = nb.sysname or active.short_hostname(n.sysname)
            nb.description = nb.description or n.sysdesc
            nb.model = nb.model or model_from_descr(n.sysdesc)
            nb.lldp_caps |= n.caps
            if n.chassis_id:
                nb.chassis_ids.add(n.chassis_id)
                self.by_chassis[n.chassis_id] = nb.id
                if n.chassis_id.count(":") == 5 and not nb.mac:
                    nb.mac = n.chassis_id
            if nb.sysname:
                self.by_name[_norm_name(nb.sysname)] = nb.id
            if n.mgmt_ip:
                self.register_ip(nb, n.mgmt_ip)
                next_ips.append(n.mgmt_ip)
            self.neighbor_links.append(Link(dev.id, nb.id, n.local_port,
                                            n.port_desc if len(n.port_desc) < 24 and n.port_desc
                                            else n.port_id, "lldp"))
        for n in data.cdp_neighbors:
            nb = self.find_device(ip=n.address, name=n.device_id)
            if nb is None:
                nid = f"cdp:{_norm_name(n.device_id) or n.address}"
                nb = self.devices.get(nid) or Device(id=nid)
                self.devices[nid] = nb
            nb.sources.add("cdp")
            nb.sysname = nb.sysname or active.short_hostname(re.sub(r"\(.*?\)", "", n.device_id))
            nb.model = nb.model or n.platform.replace("cisco ", "").replace("Cisco ", "")[:28]
            nb.description = nb.description or n.platform
            nb.cdp_caps |= n.caps
            if nb.sysname:
                self.by_name[_norm_name(nb.sysname)] = nb.id
            if n.address:
                self.register_ip(nb, n.address)
                next_ips.append(n.address)
            self.neighbor_links.append(Link(dev.id, nb.id, n.local_port, n.port, "cdp"))
        for ip, mac, _ifidx in data.arp:
            if ip in dev.all_ips() or (ip.startswith("127.") and not self._loopback_allowed()):
                continue
            host = self.device_for_ip(ip)
            host.mac = host.mac or mac
            host.sources.add("arp")
            self.l3_hint.setdefault(host.id, dev.id)
        return next_ips

    # ---------------------------------------------------------------- final
    def _finalize(self) -> None:
        devices = self.devices
        # Fabricante y gateway
        for d in devices.values():
            if d.mac and not d.vendor:
                d.vendor = vendor_for_mac(d.mac)
            if self.gateway_ip and self.gateway_ip in d.all_ips():
                d.is_gateway = True
        # Equipos cuya MAC pertenece a un equipo SNMP (otra IP del mismo router/switch)
        mac_owner: dict[str, str] = {}
        for did, data in self.snmp_data.items():
            for m in data.ifmacs:
                mac_owner.setdefault(m, did)
        for d in list(devices.values()):
            owner = mac_owner.get(d.mac)
            if owner and owner != d.id and owner in devices and not d.snmp:
                self.merge(devices[owner], d)
        for d in devices.values():
            if d.dtype not in ("internet", "unmanaged"):
                d.dtype = classify(d)

        # Raíz: puerta de enlace > equipo L3 con más enlaces > cualquiera
        gw = next((d for d in devices.values() if d.is_gateway), None)
        if gw is None and self.gateway_ip and self.cfg.mode == MODE_ACTIVE and \
                self._ip_in_targets(self.gateway_ip):
            gw = self.device_for_ip(self.gateway_ip)
            gw.is_gateway = True
            gw.dtype = classify(gw)
        if gw is None:
            degree: dict[str, int] = {}
            for l in self.neighbor_links:
                degree[l.a] = degree.get(l.a, 0) + 1
                degree[l.b] = degree.get(l.b, 0) + 1
            edge = [d for d in devices.values() if d.dtype in ("firewall", "router")]
            l3 = [d for d in devices.values() if d.dtype == "l3switch"]
            pool = edge or l3 or [d for d in devices.values() if d.snmp] or list(devices.values())
            if pool:
                gw = max(pool, key=lambda d: degree.get(d.id, 0))
        self.result.root_id = gw.id if gw else None

        if gw is not None and gw.is_gateway:
            inet = Device(id="internet", dtype="internet", sysname="Internet", sources={"gateway"})
            devices[inet.id] = inet
            self.neighbor_links.insert(0, Link(inet.id, gw.id, "", "", "internet"))

        builder = TopologyBuilder(self.result, self.snmp_data, self.l3_hint,
                                  self.cfg.detect_unmanaged, self.cfg.unmanaged_threshold)
        builder.build(self.neighbor_links)
        if gw is not None and gw.is_gateway:
            self.result.root_id = "internet"

    def _ip_in_targets(self, ip: str) -> bool:
        addr = ipaddress.IPv4Address(ip)
        for t in self.result.targets:
            try:
                if addr in ipaddress.IPv4Network(t, strict=False):
                    return True
            except ValueError:
                if t == ip:
                    return True
        return False
