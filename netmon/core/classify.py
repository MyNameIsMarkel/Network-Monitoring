"""Identificación de fabricante (OUI) y clasificación heurística del tipo de dispositivo."""
from __future__ import annotations

import re
from functools import lru_cache

from netmon.core.models import Device

try:
    import netaddr
except ImportError:  # pragma: no cover
    netaddr = None

_VENDOR_CLEAN = re.compile(r",?\s*(inc\.?|corp(oration)?\.?|co\.?,?\s*ltd\.?|ltd\.?|limited|gmbh|"
                           r"s\.?a\.?|b\.?v\.?|llc|ag|technologies|technology|international|"
                           r"electronics|communications|networks?|industries|incorporated|digital|"
                           r"semiconductor|computer|systems|trading|foundation|"
                           r"information|infocomm)\b\.?", re.I)


@lru_cache(maxsize=4096)
def vendor_for_mac(mac: str) -> str:
    if not mac or netaddr is None:
        return ""
    try:
        first = int(mac.split(":")[0], 16)
        if first & 0x02:          # MAC administrada localmente (aleatoria en móviles)
            return "MAC aleatoria"
        org = netaddr.EUI(mac).oui.registration().org
    except Exception:
        return ""
    return clean_vendor(org)


_CITY_PREFIX = re.compile(r"^(hangzhou|shenzhen|guangzhou|beijing|shanghai|xiamen|zhejiang|"
                          r"fujian|dongguan|suzhou|wuhan|chengdu|nanjing|qingdao|tianjin)\s+", re.I)


def clean_vendor(org: str) -> str:
    org = re.sub(r"\(.*?\)", "", org)
    for _ in range(2):
        org = _VENDOR_CLEAN.sub("", org).strip(" ,.-")
    org = _CITY_PREFIX.sub("", org)
    org = re.sub(r"\s{2,}", " ", org).strip(" ,.-")
    if org.isupper() and len(org) > 4:
        org = org.title()
    return org[:28]


# ---------------------------------------------------------------- reglas
FIREWALL_VENDORS = ("fortinet", "palo alto", "sophos", "sonicwall", "watchguard", "check point",
                    "barracuda", "stormshield", "netgate", "cyberoam", "zyxel usg")
NETWORK_VENDORS = ("cisco", "juniper", "aruba", "hewlett packard enterprise", "hpe", "extreme",
                   "brocade", "arista", "mikrotik", "routerboard", "ubiquiti", "netgear", "tp-link",
                   "d-link", "zyxel", "huawei", "h3c", "allied telesis", "dell emc networking",
                   "ruckus", "meraki", "cambium", "edgecore", "alcatel", "nokia", "teltonika")
AP_VENDORS = ("ruckus", "cambium", "aerohive", "meraki", "ubiquiti", "aruba", "mist", "engenius")
PRINTER_VENDORS = ("brother", "canon", "epson", "seiko epson", "lexmark", "kyocera", "ricoh",
                   "xerox", "konica", "sharp", "oki", "zebra", "toshiba tec", "hp inc")
CAMERA_VENDORS = ("hikvision", "dahua", "axis", "hanwha", "uniview", "vivotek", "mobotix",
                  "reolink", "amcrest", "bosch security", "avigilon", "foscam")
PHONE_VENDORS = ("yealink", "polycom", "poly", "grandstream", "snom", "avaya", "mitel",
                 "fanvil", "gigaset", "cisco spa", "htek", "alcatel-lucent enterprise")
NAS_VENDORS = ("synology", "qnap", "western digital", "buffalo", "asustor", "terramaster",
               "netapp")
IOT_VENDORS = ("espressif", "tuya", "shelly", "sonoff", "itead", "raspberry", "arduino",
               "philips lighting", "signify", "nest", "ring", "ecobee", "xiaomi", "amazon",
               "google", "roku", "sonos", "lg electronics", "samsung electronics visual",
               "texas instruments", "silicon labs", "nordic", "murata", "azurewave")
SERVER_VENDORS = ("vmware", "supermicro", "super micro", "proxmox", "nutanix", "citrix",
                  "xensource", "microsoft hyper", "qemu", "red hat")
MOBILE_VENDORS = ("apple", "samsung", "oneplus", "oppo", "vivo", "realme", "motorola", "huawei",
                  "honor", "xiaomi", "google")

NAME_HINTS = [
    (r"(^|[-_.])(fw|firewall|forti|pfsense|opnsense|asa)\d*([-_.]|$)", "firewall"),
    (r"(^|[-_.])(rtr|router|gw|gateway|edge|cpe)\d*([-_.]|$)", "router"),
    (r"(^|[-_.])(core|dist|l3)[-_]?sw", "l3switch"),
    (r"(^|[-_.])(sw|switch|swi|asw|csw|dsw)\d*([-_.]|$)", "switch"),
    (r"(^|[-_.])(ap|wap|uap|wifi|wlan)\d*([-_.]|$)", "ap"),
    (r"(print|prn|mfp|impresora|laser|officejet|laserjet|deskjet|ecotank)", "printer"),
    (r"(^|[-_.])(nas|diskstation|ds\d{3,4}|ts-\d{3})", "nas"),
    (r"(^|[-_.])(srv|server|servidor|dc\d*|ad\d*|esx|esxi|pve|proxmox|hyperv|vm|sql|web|mail|"
     r"exchange|backup|file)\d*([-_.]|$)", "server"),
    (r"(cam|camera|camara|nvr|dvr|ipc)", "camera"),
    (r"(phone|telefono|sip|voip|yealink|polycom)", "phone"),
    (r"(iphone|ipad|android|galaxy|pixel|redmi|movil|tablet)", "mobile"),
    (r"(desktop|laptop|portatil|pc|nb|lt|wks|ws|workstation|macbook|imac)", "pc"),
]


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def classify(dev: Device) -> str:
    """Devuelve el tipo más probable. Las evidencias fuertes (SNMP, LLDP, CDP) mandan."""
    vendor = (dev.vendor or "").lower()
    descr = (dev.description or "").lower()
    model = (dev.model or "").lower()
    name = (dev.hostname or dev.sysname or "").lower()
    ports = set(dev.open_ports)
    text = f"{descr} {model}"

    # 1. Capacidades anunciadas por LLDP / CDP
    caps = dev.lldp_caps | dev.cdp_caps
    if caps:
        if "phone" in caps:
            return "phone"
        if "ap" in caps:
            return "ap"
        if "router" in caps and "bridge" in caps:
            return "l3switch" if not _has(text + vendor, FIREWALL_VENDORS) else "firewall"
        if "router" in caps:
            return "firewall" if _has(text + vendor, FIREWALL_VENDORS) else "router"
        if "bridge" in caps:
            return "switch"

    # 2. Descripción del sistema (SNMP sysDescr / plataforma CDP)
    if text.strip():
        if _has(text, ("fortigate", "fortios", "pfsense", "opnsense", "palo alto", "pan-os",
                       "sonicwall", "sophos", "watchguard", "adaptive security appliance",
                       "check point", "gaia")):
            return "firewall"
        if _has(text, ("aironet", "access point", "wireless lan", "unifi ap", "uap-", "airos",
                       "instant on ap", "ap-3", "ap-5")):
            return "ap"
        if _has(text, ("jetdirect", "printer", "laserjet", "officejet", "mfp", "ecosys",
                       "imagerunner", "workcentre", "bizhub")):
            return "printer"
        if _has(text, ("synology", "diskstation", "qnap", "readynas")):
            return "nas"
        if _has(text, ("routeros", "isr", "asr", "edgeos", "edgerouter", "vyos", "junos srx",
                       "router")) and not _has(text, ("switch",)):
            return "router"
        if _has(text, ("catalyst", "nexus", "switch", "procurve", "arubaos-cx", "aruba jl",
                       "comware", "ex2300", "ex3400", "ex4300", "junos ex", "dgs-", "gs7",
                       "gs1", "gs3", "tl-sg", "sg350", "sg300", "cbs350", "icx", "powerconnect",
                       "dell networking", "edgeswitch", "usw-", "unifi switch")):
            if dev.sys_services is not None and dev.sys_services & 0x04:
                return "l3switch"
            return "switch"
        if _has(text, ("ip phone", "sip-", "yealink", "polycom")):
            return "phone"
        if _has(text, ("windows server", "vmware esxi", "proxmox", "hyper-v")):
            return "server"
        if "windows" in text:
            return "pc"
    if dev.sys_services is not None and dev.snmp:
        if dev.sys_services & 0x04 and dev.sys_services & 0x02:
            return "l3switch"
        if dev.sys_services & 0x02 and not dev.sys_services & 0x48:
            return "switch"
        if dev.sys_services & 0x04 and not dev.sys_services & 0x48:
            return "router"

    # 3. Puerta de enlace
    if dev.is_gateway:
        return "firewall" if _has(vendor + text, FIREWALL_VENDORS) else "router"

    # 4. Puertos abiertos
    if ports & {9100, 515, 631} and not ports & {22, 3389, 445}:
        return "printer"
    if ports & {554, 37777, 8000} and _has(vendor, CAMERA_VENDORS):
        return "camera"
    if 554 in ports and not ports & {445, 3389, 22}:
        return "camera"
    if 5060 in ports and not ports & {445, 3389}:
        return "phone"
    if ports & {5000, 5001} and _has(vendor, NAS_VENDORS):
        return "nas"
    if 8291 in ports:
        return "router"
    if ports & {88, 389, 636, 3268, 1433, 3306, 5432, 25, 143, 993}:
        return "server"
    if 902 in ports or 8006 in ports:
        return "server"
    if 62078 in ports:
        return "mobile"

    # 5. Fabricante
    if _has(vendor, FIREWALL_VENDORS):
        return "firewall"
    if _has(vendor, PRINTER_VENDORS) and not ports & {445, 3389}:
        return "printer"
    if _has(vendor, CAMERA_VENDORS):
        return "camera"
    if _has(vendor, PHONE_VENDORS):
        return "phone"
    if _has(vendor, NAS_VENDORS):
        return "nas"
    if _has(vendor, SERVER_VENDORS):
        return "server"

    # 6. Nombre de host
    for pattern, kind in NAME_HINTS:
        if name and re.search(pattern, name):
            return kind

    if _has(vendor, IOT_VENDORS) and not ports & {22, 445, 3389}:
        return "iot"
    if ports & {3389, 445, 135, 139, 5900, 548}:
        return "pc"
    if 22 in ports and dev.ttl and dev.ttl <= 64:
        return "server"
    if _has(vendor, AP_VENDORS) and ports & {22, 80, 443}:
        return "ap"
    if _has(vendor, NETWORK_VENDORS) and ports & {22, 23, 80, 443, 161}:
        return "switch"
    if vendor == "mac aleatoria" or _has(vendor, MOBILE_VENDORS):
        return "mobile"
    if dev.ttl and dev.ttl > 64 and dev.ttl <= 128:
        return "pc"
    if vendor:
        return "pc"
    return "unknown"


def model_from_descr(descr: str) -> str:
    """Extrae un modelo corto y legible del sysDescr."""
    if not descr:
        return ""
    d = descr.replace("\r", " ").replace("\n", " ")
    patterns = [
        r"(C\d{4}[A-Z0-9-]*)", r"(WS-C[\w-]+)", r"(Catalyst [\w-]+)", r"(Nexus ?\d+\w*)",
        r"(FortiGate-?\w+)", r"(RouterOS [\w.]+)", r"(CRS\d+[\w-]*|CCR\d+[\w-]*|RB\d+[\w-]*)",
        r"(JL\d{3}A)", r"(Aruba [\w-]+)", r"(EX\d{4}[\w-]*)", r"(SRX\d+)", r"(ISR ?\d+\w*)",
        r"(T1600G[\w-]*|TL-SG[\w-]*|SG\d{3,4}[\w-]*)", r"(GS\d{3,4}[\w-]*)", r"(US-\d+[\w-]*)",
        r"(USW-[\w-]+)", r"(DGS-[\w-]+)", r"(ProCurve [\w ]+?Switch [\w-]+)",
    ]
    for p in patterns:
        m = re.search(p, d)
        if m:
            return m.group(1)[:28]
    first = re.split(r"[,;]", d)[0].strip()
    return first[:28]
