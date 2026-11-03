"""Genera una red de prueba simulada (snmpsim) con LLDP, CDP, ARP y tablas MAC.

Topología:
    rtr-edge (127.0.0.10) ── sw-core (127.0.0.11) ─┬─ sw-acc-1 (127.0.0.12) ── ap-planta1 (LLDP)
                                                    └─ sw-acc-2 (127.0.0.13) ── teléfono (CDP)
Uso:
    python make_sim.py <carpeta_salida>
    snmpsim-command-responder --data-dir=<carpeta>/rtr --agent-udpv4-endpoint=127.0.0.10:161 ...
"""
import sys
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "sim")

LLDP_REM = "1.0.8802.1.1.2.1.4.1.1"
LLDP_MAN = "1.0.8802.1.1.2.1.4.2.1.3"
CDP = "1.3.6.1.4.1.9.9.23.1.2.1.1"


def mac_hex(m: str) -> str:
    return m.replace(":", "")


def mac_oid(m: str) -> str:
    return ".".join(str(int(x, 16)) for x in m.split(":"))


def ip_hex(ip: str) -> str:
    return "".join(f"{int(x):02x}" for x in ip.split("."))


class Dev:
    def __init__(self, name, ip, descr, services, chassis):
        self.rows: dict[str, tuple[str, str]] = {}
        self.ip, self.chassis = ip, chassis
        self.set("1.3.6.1.2.1.1.1.0", "4", descr)
        self.set("1.3.6.1.2.1.1.2.0", "6", "1.3.6.1.4.1.9.1.1")
        self.set("1.3.6.1.2.1.1.5.0", "4", name)
        self.set("1.3.6.1.2.1.1.6.0", "4", "CPD Bilbao")
        self.set("1.3.6.1.2.1.1.7.0", "2", str(services))
        self.set("1.0.8802.1.1.2.1.3.2.0", "4x", mac_hex(chassis))
        self.set(f"1.3.6.1.2.1.4.20.1.2.{ip}", "2", "100")
        self.set(f"1.3.6.1.2.1.4.20.1.3.{ip}", "64", "255.255.255.0")
        self.iface(100, "Vlan1", chassis, 1000)
        self._lldp_idx = 0

    def set(self, oid, typ, val):
        self.rows[oid] = (typ, val)

    def iface(self, idx, name, mac="", speed=1000):
        self.set(f"1.3.6.1.2.1.2.2.1.2.{idx}", "4", name)
        self.set(f"1.3.6.1.2.1.31.1.1.1.1.{idx}", "4", name)
        self.set(f"1.3.6.1.2.1.31.1.1.1.15.{idx}", "66", str(speed))
        if mac:
            self.set(f"1.3.6.1.2.1.2.2.1.6.{idx}", "4x", mac_hex(mac))
        self.set(f"1.3.6.1.2.1.17.1.4.1.2.{idx}", "2", str(idx))

    def lldp(self, lport, sysname, chassis, port, caps, mgmt=""):
        base = f"0.{lport}.1"
        self.set(f"{LLDP_REM}.4.{base}", "2", "4")
        self.set(f"{LLDP_REM}.5.{base}", "4x", mac_hex(chassis))
        self.set(f"{LLDP_REM}.6.{base}", "2", "5")
        self.set(f"{LLDP_REM}.7.{base}", "4", port)
        self.set(f"{LLDP_REM}.8.{base}", "4", port)
        self.set(f"{LLDP_REM}.9.{base}", "4", sysname)
        self.set(f"{LLDP_REM}.10.{base}", "4", f"{sysname} system")
        self.set(f"{LLDP_REM}.11.{base}", "4x", caps)
        self.set(f"{LLDP_REM}.12.{base}", "4x", caps)
        if mgmt:
            self.set(f"{LLDP_MAN}.{base}.1.4.{mgmt}", "2", "2")

    def cdp(self, ifidx, devid, addr, port, platform, caps):
        b = f"{ifidx}.1"
        self.set(f"{CDP}.3.{b}", "2", "1")
        self.set(f"{CDP}.4.{b}", "4x", ip_hex(addr) if addr else "")
        self.set(f"{CDP}.6.{b}", "4", devid)
        self.set(f"{CDP}.7.{b}", "4", port)
        self.set(f"{CDP}.8.{b}", "4", platform)
        self.set(f"{CDP}.9.{b}", "4x", caps)

    def fdb(self, mac, port):
        self.set(f"1.3.6.1.2.1.17.4.3.1.2.{mac_oid(mac)}", "2", str(port))

    def arp(self, ifidx, ip, mac):
        self.set(f"1.3.6.1.2.1.4.22.1.2.{ifidx}.{ip}", "4x", mac_hex(mac))

    def write(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        key = lambda o: tuple(int(x) for x in o.split("."))
        lines = [f"{o}|{t}|{v}" for o, (t, v) in sorted(self.rows.items(), key=lambda kv: key(kv[0]))]
        (folder / "public.snmprec").write_text("\n".join(lines) + "\n")


# ------------------------------------------------------------------ equipos
R_MAC, C_MAC, A1_MAC, A2_MAC = "00:1e:7a:10:00:01", "00:1e:7a:11:00:01", "94:18:82:12:00:01", \
    "00:1e:7a:13:00:01"
AP_MAC, PHONE_MAC = "94:18:82:30:00:01", "00:1e:7a:31:00:01"

rtr = Dev("rtr-edge", "127.0.0.10", "Cisco IOS XE Software, ISR4331 Software (X86_64_LINUX_IOSD)",
          78, R_MAC)
core = Dev("sw-core.empresa.local", "127.0.0.11",
           "Cisco IOS Software [Cupertino], Catalyst L3 Switch Software (CAT9K_IOSXE)", 6, C_MAC)
acc1 = Dev("sw-acc-1", "127.0.0.12", "Aruba JL322A 2930M-48G-PoE+ Switch, revision WC.16.10",
           2, A1_MAC)
acc2 = Dev("sw-acc-2", "127.0.0.13", "Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M)",
           2, A2_MAC)

rtr.iface(1, "Gi0/0/0", "00:1e:7a:10:00:02")
rtr.iface(2, "Gi0/0/1", "00:1e:7a:10:00:03")
rtr.lldp(2, "sw-core.empresa.local", C_MAC, "Gi1/0/48", "2800", "127.0.0.11")

core.iface(1, "Gi1/0/1", "", 10000)
core.iface(2, "Gi1/0/2", "", 10000)
core.iface(10, "Gi1/0/10")
core.iface(11, "Gi1/0/11")
core.iface(12, "Gi1/0/12")
core.iface(48, "Gi1/0/48")
core.lldp(48, "rtr-edge", R_MAC, "Gi0/0/1", "0800", "127.0.0.10")
core.lldp(1, "sw-acc-1", A1_MAC, "49", "2000", "127.0.0.12")
core.lldp(2, "sw-acc-2", A2_MAC, "Gi0/1", "2000", "127.0.0.13")

acc1.iface(49, "49", "", 10000)
for p in range(1, 25):
    acc1.iface(p, str(p))
acc1.lldp(49, "sw-core", C_MAC, "Gi1/0/1", "2800", "127.0.0.11")
acc1.lldp(5, "ap-planta1", AP_MAC, "eth0", "1000", "127.0.0.30")

acc2.iface(1, "Gi0/1", "", 1000)
for p in range(1, 25):
    acc2.iface(100 + p, f"Fa0/{p}", "", 100)
acc2.cdp(1, "sw-core.empresa.local(FOC2233X0AB)", "127.0.0.11", "GigabitEthernet1/0/2",
         "cisco C9300-48P", "00000028")
acc2.cdp(103, "SEP001E7A310001", "127.0.0.40", "Port 1", "Cisco IP Phone 8841", "00000090")

# Hosts: (ip, mac, switch, puerto)
hosts = [
    ("127.0.0.50", "00:50:56:aa:00:01", "core", 10),   # ESXi/VM
    ("127.0.0.51", "ac:1f:6b:aa:00:02", "core", 11),   # Supermicro servidor
    ("127.0.0.52", "00:11:32:aa:00:03", "core", 12),   # Synology NAS
    ("127.0.0.60", "00:14:22:bb:00:01", "acc1", 10),
    ("127.0.0.61", "d0:67:e5:bb:00:02", "acc1", 11),
    ("127.0.0.62", "a4:4c:c8:bb:00:03", "acc1", 12),
    ("127.0.0.63", "00:1b:21:bb:00:04", "acc1", 13),
    ("127.0.0.64", "88:51:fb:bb:00:05", "acc1", 14),
    ("127.0.0.65", "44:19:b6:bb:00:06", "acc1", 20),   # cámara Hikvision
    ("127.0.0.66", "f0:18:98:bb:00:07", "acc1", 5),    # MacBook por WiFi (detrás del AP)
    ("127.0.0.67", "24:0a:c4:bb:00:08", "acc1", 5),    # sensor ESP32 por WiFi
    ("127.0.0.70", "00:1b:a9:cc:00:01", "acc2", 107),  # impresora Brother
    ("127.0.0.71", "3c:2a:f4:cc:00:02", "acc2", 108),  # impresora Brother 2
    ("127.0.0.72", "00:14:22:cc:00:03", "acc2", 103),  # PC detrás del teléfono
    ("127.0.0.73", "00:e0:4c:cc:00:04", "acc2", 112),  # switch de mesa no gestionado
    ("127.0.0.74", "a4:4c:c8:cc:00:05", "acc2", 112),
    ("127.0.0.75", "00:14:22:cc:00:06", "acc2", 112),
    ("127.0.0.76", "b8:27:eb:cc:00:07", "acc2", 112),
    ("127.0.0.77", "80:5e:c0:cc:00:08", "acc2", 104),  # teléfono Yealink
]
uplink = {"acc1": ("core", 1), "acc2": ("core", 2)}
sw = {"core": core, "acc1": acc1, "acc2": acc2}
# Puertos troncales (hacia arriba) en cada switch de acceso
acc_up = {"acc1": 49, "acc2": 1}

for ip, mac, s, port in hosts:
    rtr.arp(2, ip, mac)
    sw[s].fdb(mac, port)
    if s in uplink:
        core.fdb(mac, uplink[s][1])
    for other, up in acc_up.items():
        if other != s:
            sw[other].fdb(mac, up)
    core.fdb(R_MAC, 48)

for name, ip, mac in (("core", "127.0.0.11", C_MAC), ("acc1", "127.0.0.12", A1_MAC),
                      ("acc2", "127.0.0.13", A2_MAC)):
    rtr.arp(2, ip, mac)
rtr.arp(2, "127.0.0.30", AP_MAC)
rtr.arp(2, "127.0.0.40", PHONE_MAC)
acc1.fdb(AP_MAC, 5)
acc2.fdb(PHONE_MAC, 103)
core.fdb(AP_MAC, 1)
core.fdb(PHONE_MAC, 2)
for s, up in acc_up.items():
    sw[s].fdb(R_MAC, up)

for name, d in (("rtr", rtr), ("core", core), ("acc1", acc1), ("acc2", acc2)):
    d.write(OUT / name)
print(f"Datos de simulación escritos en {OUT}")
