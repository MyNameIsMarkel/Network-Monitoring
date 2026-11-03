"""Pruebas sin red: topología, generación del .drawio y lectura con el lector propio."""
from datetime import datetime

from netmon.core.classify import classify
from netmon.core.models import Device, Link, ScanResult
from netmon.drawio.reader import read_drawio
from netmon.drawio.writer import build_drawio, save_drawio


def sample_result() -> ScanResult:
    r = ScanResult(mode="passive", started=datetime(2026, 11, 3, 10, 0))
    devs = [
        Device(id="internet", dtype="internet", sysname="Internet"),
        Device(id="gw", ip="192.168.1.1", sysname="fw-edge", dtype="firewall", is_gateway=True),
        Device(id="core", ip="192.168.1.2", sysname="sw-core", dtype="l3switch", model="C9300"),
        Device(id="acc", ip="192.168.1.3", sysname="sw-acc", dtype="switch"),
        Device(id="ap", ip="192.168.1.30", sysname="ap-1", dtype="ap"),
    ]
    for i in range(14):
        devs.append(Device(id=f"h{i}", ip=f"192.168.1.{50 + i}", dtype="pc", vendor="Dell",
                           attach_port=f"Gi1/0/{i + 1}"))
    for d in devs:
        r.devices[d.id] = d
    r.links = [Link("internet", "gw", kind="internet"),
               Link("gw", "core", "port1", "Gi1/0/48", "lldp", "1G"),
               Link("core", "acc", "Gi1/0/1", "49", "lldp", "10G"),
               Link("acc", "ap", "5", "eth0", "lldp"),
               Link("core", "gw", "Gi1/0/47", "port2", "lldp")]   # enlace redundante
    r.links += [Link("acc", f"h{i}", f"Gi1/0/{i + 1}", "", "fdb") for i in range(14)]
    r.root_id = "internet"
    r.finished = datetime(2026, 11, 3, 10, 1)
    return r


def test_drawio_roundtrip(tmp_path):
    path = save_drawio(sample_result(), tmp_path)
    assert path.suffix == ".drawio" and path.exists()
    pages = read_drawio(path)
    cells = pages[0].cells
    devices = [c for c in cells.values() if c.attrs.get("nm_type")]
    assert len(devices) == 19
    edges = [c for c in cells.values() if c.edge and (c.source or c.target)]
    assert len(edges) == 19          # 18 del árbol + 1 redundante
    for e in edges:
        assert e.source in cells and e.target in cells
    # cada icono es un SVG incrustado
    assert all(c.style.get("image", "").startswith("data:image/svg+xml,") for c in devices)


def test_xml_is_valid_mxfile():
    xml = build_drawio(sample_result())
    assert xml.startswith("<mxfile") and "<mxGraphModel" in xml and 'id="0"' in xml


def test_classify_basics():
    assert classify(Device(id="a", lldp_caps={"bridge"})) == "switch"
    assert classify(Device(id="b", lldp_caps={"router", "bridge"})) == "l3switch"
    assert classify(Device(id="c", open_ports=[9100, 80])) == "printer"
    assert classify(Device(id="d", description="FortiGate-60F v7.2", snmp=True)) == "firewall"
    assert classify(Device(id="e", is_gateway=True)) == "router"
