#!/usr/bin/env bash
# Instalador para cualquier distribución Linux (sin .deb).
#   ./install.sh            -> instala para el usuario actual (~/.local)
#   sudo ./install.sh       -> instala para todo el sistema (/opt)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "$(id -u)" -eq 0 ]; then
  PREFIX=/opt/network-monitoring; BIN=/usr/local/bin
  APPS=/usr/share/applications; ICONS=/usr/share/icons/hicolor/256x256/apps
else
  PREFIX="$HOME/.local/opt/network-monitoring"; BIN="$HOME/.local/bin"
  APPS="$HOME/.local/share/applications"; ICONS="$HOME/.local/share/icons/hicolor/256x256/apps"
fi
if [ "${1:-}" = "--uninstall" ]; then
  rm -rf "$PREFIX" "$BIN/netmon" "$APPS/network-monitoring.desktop" "$ICONS/network-monitoring.png"
  echo "Network Monitoring desinstalado."; exit 0
fi
mkdir -p "$PREFIX" "$BIN" "$APPS" "$ICONS"
rm -rf "$PREFIX"
cp -a "$HERE/app" "$PREFIX"
ln -sf "$PREFIX/netmon" "$BIN/netmon"
cp "$HERE/icon.png" "$ICONS/network-monitoring.png"
sed "s|^Exec=.*|Exec=$PREFIX/netmon %f|" "$HERE/network-monitoring.desktop" > "$APPS/network-monitoring.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS" || true
echo "Instalado en $PREFIX"
echo "Ábrelo desde el menú de aplicaciones o ejecuta: netmon"
if ! ldconfig -p 2>/dev/null | grep -q libxcb-cursor; then
  echo "Aviso: si la ventana no abre, instala libxcb-cursor0 (Debian/Ubuntu) o xcb-util-cursor (Fedora/Arch)."
fi
