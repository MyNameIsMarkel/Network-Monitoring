"""Cliente SNMP (v2c / v3) y recolección de LLDP, CDP, ARP, FDB e interfaces.

Solo se usan operaciones de lectura (GET / GETBULK): el impacto en la red es mínimo y
no se modifica nada en los equipos.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget,
    UsmUserData, bulk_walk_cmd, get_cmd,
    usmAesCfb128Protocol, usmAesCfb256Protocol, usmDESPrivProtocol, usmHMAC192SHA256AuthProtocol,
    usmHMAC384SHA512AuthProtocol, usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol,
    usmNoAuthProtocol, usmNoPrivProtocol,
)

from netmon.core.models import SnmpCredentials

# --------------------------------------------------------------------------- OIDs
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECTID = "1.3.6.1.2.1.1.2.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
SYS_SERVICES = "1.3.6.1.2.1.1.7.0"

IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_PHYS = "1.3.6.1.2.1.2.2.1.6"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_HIGHSPEED = "1.3.6.1.2.1.31.1.1.1.15"
IP_AD_IFINDEX = "1.3.6.1.2.1.4.20.1.2"
IP_AD_MASK = "1.3.6.1.2.1.4.20.1.3"
IP_NET_TO_MEDIA = "1.3.6.1.2.1.4.22.1.2"

LLDP_LOC_CHASSIS = "1.0.8802.1.1.2.1.3.2.0"
LLDP_LOC_PORT_ID = "1.0.8802.1.1.2.1.3.7.1.3"
LLDP_LOC_PORT_DESC = "1.0.8802.1.1.2.1.3.7.1.4"
LLDP_REM = "1.0.8802.1.1.2.1.4.1.1"
LLDP_REM_MAN_ADDR = "1.0.8802.1.1.2.1.4.2.1.3"

CDP_CACHE = "1.3.6.1.4.1.9.9.23.1.2.1.1"

DOT1D_BASEPORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
DOT1D_FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"
DOT1Q_FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2"

_AUTH = {
    "none": usmNoAuthProtocol, "MD5": usmHMACMD5AuthProtocol, "SHA": usmHMACSHAAuthProtocol,
    "SHA-256": usmHMAC192SHA256AuthProtocol, "SHA-512": usmHMAC384SHA512AuthProtocol,
}
_PRIV = {
    "none": usmNoPrivProtocol, "DES": usmDESPrivProtocol, "AES-128": usmAesCfb128Protocol,
    "AES-256": usmAesCfb256Protocol,
}

# Bits LLDP (BITS: el bit 0 es el más significativo del primer octeto)
_LLDP_CAP_BITS = {1: "repeater", 2: "bridge", 3: "ap", 4: "router", 5: "phone", 7: "station"}
# Bits CDP (entero de 32 bits)
_CDP_CAP_BITS = {0x01: "router", 0x02: "bridge", 0x08: "bridge", 0x10: "station", 0x80: "phone"}


def _oid(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in s.split("."))


def _is_error_value(val) -> bool:
    return val.__class__.__name__ in ("NoSuchObject", "NoSuchInstance", "EndOfMibView", "Null")


def to_bytes(val) -> bytes:
    try:
        return bytes(val.asOctets())
    except AttributeError:
        return str(val).encode()


def to_text(val) -> str:
    if val is None or _is_error_value(val):
        return ""
    if hasattr(val, "asOctets"):
        raw = bytes(val.asOctets())
        if val.__class__.__name__ == "IpAddress" and len(raw) == 4:
            return ".".join(str(b) for b in raw)
        try:
            txt = raw.decode("utf-8")
            if all(c.isprintable() or c in "\r\n\t" for c in txt):
                return txt.strip("\x00").strip()
        except UnicodeDecodeError:
            pass
        return raw.hex(":")
    return val.prettyPrint()


def to_int(val, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def mac_from_bytes(raw: bytes) -> str:
    if len(raw) == 6:
        return ":".join(f"{b:02x}" for b in raw)
    txt = raw.decode("ascii", "ignore")
    from netmon.core.netinfo import normalize_mac
    return normalize_mac(txt)


@dataclass
class LldpNeighbor:
    local_port: str
    chassis_id: str = ""
    port_id: str = ""
    port_desc: str = ""
    sysname: str = ""
    sysdesc: str = ""
    caps: set[str] = field(default_factory=set)
    mgmt_ip: str = ""


@dataclass
class CdpNeighbor:
    local_port: str
    device_id: str = ""
    address: str = ""
    port: str = ""
    platform: str = ""
    caps: set[str] = field(default_factory=set)


@dataclass
class SnmpDeviceData:
    ip: str
    sysdescr: str = ""
    sysobjectid: str = ""
    sysname: str = ""
    syslocation: str = ""
    sysservices: int | None = None
    ifnames: dict[int, str] = field(default_factory=dict)
    ifspeed: dict[int, int] = field(default_factory=dict)
    ifmacs: set[str] = field(default_factory=set)
    ip_addrs: dict[str, tuple[int, str]] = field(default_factory=dict)
    arp: list[tuple[str, str, int]] = field(default_factory=list)
    lldp_chassis: str = ""
    lldp_neighbors: list[LldpNeighbor] = field(default_factory=list)
    cdp_neighbors: list[CdpNeighbor] = field(default_factory=list)
    fdb: dict[str, str] = field(default_factory=dict)          # MAC -> nombre de puerto
    port_mac_count: dict[str, int] = field(default_factory=dict)


class SnmpClient:
    def __init__(self, creds: SnmpCredentials):
        self.creds = creds
        self.engine = SnmpEngine()
        self._auth_for: dict[str, object] = {}

    def _auth_options(self) -> list[object]:
        c = self.creds
        if c.version == "3":
            auth = _AUTH.get(c.auth_protocol, usmHMACSHAAuthProtocol)
            priv = _PRIV.get(c.priv_protocol, usmAesCfb128Protocol)
            if auth is usmNoAuthProtocol:
                return [UsmUserData(c.username)]
            if priv is usmNoPrivProtocol:
                return [UsmUserData(c.username, authKey=c.auth_key, authProtocol=auth)]
            return [UsmUserData(c.username, authKey=c.auth_key, privKey=c.priv_key,
                                authProtocol=auth, privProtocol=priv)]
        comms = [x for x in c.communities if x] or ["public"]
        return [CommunityData(x, mpModel=1) for x in comms]

    async def _target(self, ip: str, timeout: float | None = None, retries: int | None = None):
        return await UdpTransportTarget.create(
            (ip, self.creds.port),
            timeout=self.creds.timeout if timeout is None else timeout,
            retries=self.creds.retries if retries is None else retries)

    async def probe(self, ip: str, timeout: float | None = None, retries: int | None = None) -> bool:
        """Comprueba si el equipo responde a SNMP con alguna de las credenciales."""
        for auth in self._auth_options():
            try:
                target = await self._target(ip, timeout, retries)
                err, status, _, binds = await get_cmd(
                    self.engine, auth, target, ContextData(),
                    ObjectType(ObjectIdentity(SYS_OBJECTID)), lookupMib=False)
            except Exception:
                continue
            if not err and not status and binds and not _is_error_value(binds[0][1]):
                self._auth_for[ip] = auth
                return True
        return False

    async def get(self, ip: str, oids: list[str]) -> dict[str, object]:
        auth = self._auth_for.get(ip)
        if auth is None:
            return {}
        try:
            target = await self._target(ip)
            err, status, _, binds = await get_cmd(
                self.engine, auth, target, ContextData(),
                *[ObjectType(ObjectIdentity(o)) for o in oids], lookupMib=False)
        except Exception:
            return {}
        if err or status:
            return {}
        return {".".join(str(x) for x in tuple(b[0])): b[1] for b in binds}

    async def walk(self, ip: str, base: str, max_rows: int = 20000) -> list[tuple[tuple[int, ...], object]]:
        """GETBULK walk de una subtabla. Devuelve [(índice_relativo, valor)]."""
        auth = self._auth_for.get(ip)
        if auth is None:
            return []
        base_t = _oid(base)
        rows: list[tuple[tuple[int, ...], object]] = []
        try:
            target = await self._target(ip)
            async for err, status, _, binds in bulk_walk_cmd(
                    self.engine, auth, target, ContextData(), 0, 30,
                    ObjectType(ObjectIdentity(base)), lexicographicMode=False, lookupMib=False):
                if err or status:
                    break
                for b in binds:
                    oid_t = tuple(b[0])
                    if oid_t[:len(base_t)] != base_t or _is_error_value(b[1]):
                        return rows
                    rows.append((oid_t[len(base_t):], b[1]))
                if len(rows) >= max_rows:
                    break
        except Exception:
            pass
        return rows

    # ------------------------------------------------------------------ recolección
    async def collect(self, ip: str) -> SnmpDeviceData:
        d = SnmpDeviceData(ip=ip)
        sysv = await self.get(ip, [SYS_DESCR, SYS_OBJECTID, SYS_NAME, SYS_LOCATION, SYS_SERVICES])
        d.sysdescr = to_text(sysv.get(SYS_DESCR))
        d.sysobjectid = to_text(sysv.get(SYS_OBJECTID))
        d.sysname = to_text(sysv.get(SYS_NAME))
        d.syslocation = to_text(sysv.get(SYS_LOCATION))
        if sysv.get(SYS_SERVICES) is not None and not _is_error_value(sysv[SYS_SERVICES]):
            d.sysservices = to_int(sysv[SYS_SERVICES])

        (ifname, ifdescr, ifspeed, ifphys, ipidx, ipmask, arp, lldp_ports, lldp_desc,
         lldp_rem, lldp_man, cdp, chassis) = await asyncio.gather(
            self.walk(ip, IF_NAME), self.walk(ip, IF_DESCR), self.walk(ip, IF_HIGHSPEED),
            self.walk(ip, IF_PHYS), self.walk(ip, IP_AD_IFINDEX), self.walk(ip, IP_AD_MASK),
            self.walk(ip, IP_NET_TO_MEDIA), self.walk(ip, LLDP_LOC_PORT_ID),
            self.walk(ip, LLDP_LOC_PORT_DESC), self.walk(ip, LLDP_REM, 8000),
            self.walk(ip, LLDP_REM_MAN_ADDR), self.walk(ip, CDP_CACHE, 8000),
            self.get(ip, [LLDP_LOC_CHASSIS]))

        for idx, v in ifdescr:
            d.ifnames[idx[0]] = to_text(v)
        for idx, v in ifname:            # ifName es más corto (Gi1/0/1) y se prefiere
            t = to_text(v)
            if t:
                d.ifnames[idx[0]] = t
        for idx, v in ifspeed:
            d.ifspeed[idx[0]] = to_int(v)
        for idx, v in ifphys:
            mac = mac_from_bytes(to_bytes(v))
            if mac and mac != "00:00:00:00:00:00":
                d.ifmacs.add(mac)
        masks = {".".join(map(str, idx)): to_text(v) for idx, v in ipmask}
        for idx, v in ipidx:
            a = ".".join(map(str, idx))
            d.ip_addrs[a] = (to_int(v), masks.get(a, ""))
        for idx, v in arp:
            if len(idx) >= 5:
                mac = mac_from_bytes(to_bytes(v))
                if mac and mac not in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
                    d.arp.append((".".join(map(str, idx[1:5])), mac, idx[0]))
        if chassis.get(LLDP_LOC_CHASSIS) is not None:
            d.lldp_chassis = _chassis_text(to_bytes(chassis[LLDP_LOC_CHASSIS]))

        loc_port_names: dict[int, str] = {}
        for idx, v in lldp_desc:
            loc_port_names[idx[0]] = to_text(v)
        for idx, v in lldp_ports:
            t = to_text(v)
            if t and (idx[0] not in loc_port_names or len(t) < len(loc_port_names[idx[0]])):
                loc_port_names[idx[0]] = t

        def local_name(portnum: int) -> str:
            # lldpLocPortNum suele coincidir con ifIndex; si no, se usa el id LLDP local
            if portnum in d.ifnames and (portnum not in loc_port_names or
                                         loc_port_names[portnum] == d.ifnames[portnum]):
                return d.ifnames[portnum]
            return loc_port_names.get(portnum) or d.ifnames.get(portnum) or f"puerto {portnum}"

        d.lldp_neighbors = _parse_lldp(lldp_rem, lldp_man, local_name)
        d.cdp_neighbors = _parse_cdp(cdp, lambda i: d.ifnames.get(i, f"if{i}"))
        return d

    async def collect_fdb(self, ip: str, d: SnmpDeviceData) -> None:
        """Tabla de direcciones MAC del switch (qué MAC hay detrás de cada puerto)."""
        baseport = {idx[0]: to_int(v) for idx, v in await self.walk(ip, DOT1D_BASEPORT_IFINDEX)}

        def port_name(bridge_port: int) -> str:
            ifidx = baseport.get(bridge_port, bridge_port)
            return d.ifnames.get(ifidx, f"puerto {bridge_port}")

        rows = await self.walk(ip, DOT1Q_FDB_PORT, 30000)
        entries: list[tuple[str, int]] = []
        for idx, v in rows:              # índice: fdbId.MAC(6)
            if len(idx) >= 7:
                entries.append((":".join(f"{b:02x}" for b in idx[-6:]), to_int(v)))
        if not entries:
            for idx, v in await self.walk(ip, DOT1D_FDB_PORT, 30000):
                if len(idx) >= 6:
                    entries.append((":".join(f"{b:02x}" for b in idx[-6:]), to_int(v)))
        for mac, bp in entries:
            if bp <= 0:
                continue
            name = port_name(bp)
            d.fdb[mac] = name
        counts: dict[str, int] = {}
        for name in d.fdb.values():
            counts[name] = counts.get(name, 0) + 1
        d.port_mac_count = counts

    def close(self) -> None:
        try:
            self.engine.close_dispatcher()
        except Exception:
            pass


def _chassis_text(raw: bytes, subtype: int | None = None) -> str:
    if subtype == 4 or (subtype is None and len(raw) == 6):
        return ":".join(f"{b:02x}" for b in raw)
    if subtype == 5 and len(raw) == 5 and raw[0] == 1:
        return ".".join(str(b) for b in raw[1:])
    try:
        txt = raw.decode("utf-8")
        if txt.isprintable():
            return txt
    except UnicodeDecodeError:
        pass
    return raw.hex(":")


def _caps_from_bits(raw: bytes) -> set[str]:
    caps: set[str] = set()
    if not raw:
        return caps
    val = raw[0] << 8 | (raw[1] if len(raw) > 1 else 0)
    for bit, name in _LLDP_CAP_BITS.items():
        if val & (0x8000 >> bit):
            caps.add(name)
    return caps


def _parse_lldp(rem_rows, man_rows, local_name) -> list[LldpNeighbor]:
    # índice de la tabla remota: columna.timeMark.localPort.remIndex
    neighbors: dict[tuple[int, int], dict[int, object]] = {}
    for idx, v in rem_rows:
        if len(idx) < 4:
            continue
        col, _tm, lport, rindex = idx[0], idx[1], idx[2], idx[3]
        neighbors.setdefault((lport, rindex), {})[col] = v
    mgmt: dict[tuple[int, int], str] = {}
    for idx, _v in man_rows:
        # timeMark.localPort.remIndex.addrSubtype.addrLen.addr...
        if len(idx) >= 9 and idx[3] == 1 and idx[4] == 4:
            mgmt.setdefault((idx[1], idx[2]), ".".join(map(str, idx[5:9])))
    out: list[LldpNeighbor] = []
    for (lport, rindex), cols in neighbors.items():
        chassis_sub = to_int(cols.get(4), 0)
        port_sub = to_int(cols.get(6), 0)
        port_raw = to_bytes(cols[7]) if 7 in cols else b""
        if port_sub == 3 and len(port_raw) == 6:
            port_id = ":".join(f"{b:02x}" for b in port_raw)
        else:
            port_id = to_text(cols.get(7)) if 7 in cols else ""
        n = LldpNeighbor(
            local_port=local_name(lport),
            chassis_id=_chassis_text(to_bytes(cols[5]), chassis_sub) if 5 in cols else "",
            port_id=port_id,
            port_desc=to_text(cols.get(8)) if 8 in cols else "",
            sysname=to_text(cols.get(9)) if 9 in cols else "",
            sysdesc=to_text(cols.get(10)) if 10 in cols else "",
            caps=_caps_from_bits(to_bytes(cols[12])) if 12 in cols else
            (_caps_from_bits(to_bytes(cols[11])) if 11 in cols else set()),
            mgmt_ip=mgmt.get((lport, rindex), ""),
        )
        if chassis_sub == 5 and not n.mgmt_ip and n.chassis_id.count(".") == 3:
            n.mgmt_ip = n.chassis_id
        out.append(n)
    return out


def _parse_cdp(rows, ifname) -> list[CdpNeighbor]:
    entries: dict[tuple[int, int], dict[int, object]] = {}
    for idx, v in rows:
        if len(idx) < 3:
            continue
        entries.setdefault((idx[1], idx[2]), {})[idx[0]] = v
    out: list[CdpNeighbor] = []
    for (ifidx, _dev), cols in entries.items():
        addr = ""
        if 4 in cols:
            raw = to_bytes(cols[4])
            if len(raw) == 4:
                addr = ".".join(str(b) for b in raw)
        caps: set[str] = set()
        if 9 in cols:
            raw = to_bytes(cols[9])
            val = int.from_bytes(raw[-4:], "big") if raw else 0
            for bit, name in _CDP_CAP_BITS.items():
                if val & bit:
                    caps.add(name)
        out.append(CdpNeighbor(
            local_port=ifname(ifidx), device_id=to_text(cols.get(6)) if 6 in cols else "",
            address=addr, port=to_text(cols.get(7)) if 7 in cols else "",
            platform=to_text(cols.get(8)) if 8 in cols else "", caps=caps))
    return out
