#!/usr/bin/env bash
# Empaqueta dist/NetworkMonitoring (PyInstaller) como .deb y como .tar.gz con instalador.
#   bash packaging/linux/build_linux.sh 1.0.0
set -euo pipefail
VERSION="${1:-1.0.0}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="$ROOT/dist"
APP="$DIST/NetworkMonitoring"
[ -x "$APP/netmon" ] || { echo "Falta $APP/netmon: ejecuta antes pyinstaller packaging/netmon.spec"; exit 1; }

# ------------------------------------------------------------------ .deb
PKG="$DIST/deb/network-monitoring_${VERSION}_amd64"
rm -rf "$DIST/deb"
mkdir -p "$PKG/DEBIAN" "$PKG/opt/network-monitoring" "$PKG/usr/bin" \
         "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps" \
         "$PKG/usr/share/icons/hicolor/scalable/apps"
cp -a "$APP/." "$PKG/opt/network-monitoring/"
ln -s /opt/network-monitoring/netmon "$PKG/usr/bin/netmon"
cp "$ROOT/packaging/linux/network-monitoring.desktop" "$PKG/usr/share/applications/"
cp "$ROOT/netmon/assets/icon.png" "$PKG/usr/share/icons/hicolor/256x256/apps/network-monitoring.png"
cp "$ROOT/netmon/assets/icon.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/network-monitoring.svg"
SIZE=$(du -sk "$PKG" | cut -f1)
cat > "$PKG/DEBIAN/control" <<EOF
Package: network-monitoring
Version: ${VERSION}
Section: net
Priority: optional
Architecture: amd64
Installed-Size: ${SIZE}
Depends: libxcb-cursor0, libxkbcommon-x11-0, libegl1, libfontconfig1, iputils-ping
Maintainer: MyNameIsMarkel <noreply@github.com>
Homepage: https://github.com/MyNameIsMarkel/Network-Monitoring
Description: Mapeo automático de red con diagramas draw.io
 Descubre la topología de la red por SNMP + LLDP/CDP (impacto mínimo) o con un
 escaneo activo completo, y genera un diagrama .drawio con iconos y conexiones.
EOF
cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
command -v update-desktop-database >/dev/null && update-desktop-database -q || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
exit 0
EOF
chmod 755 "$PKG/DEBIAN/postinst"
dpkg-deb --build --root-owner-group "$PKG" "$DIST/network-monitoring_${VERSION}_amd64.deb"

# ------------------------------------------------------------------ .tar.gz (otras distros)
TGZ_DIR="$DIST/tgz/network-monitoring-${VERSION}"
rm -rf "$DIST/tgz"
mkdir -p "$TGZ_DIR"
cp -a "$APP" "$TGZ_DIR/app"
cp "$ROOT/packaging/linux/install.sh" "$ROOT/packaging/linux/network-monitoring.desktop" \
   "$ROOT/netmon/assets/icon.png" "$TGZ_DIR/"
chmod +x "$TGZ_DIR/install.sh"
tar -C "$DIST/tgz" -czf "$DIST/network-monitoring-${VERSION}-linux-x86_64.tar.gz" \
    "network-monitoring-${VERSION}"
echo "Paquetes generados en $DIST"
