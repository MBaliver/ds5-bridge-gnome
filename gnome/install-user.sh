#!/bin/sh
# Installs the GNOME layer for the current user from this checkout:
#   - ds5-bridged as a systemd user service (+ D-Bus activation)
#   - a ds5-bridge.desktop override that opens the UI client instead of the
#     packaged Electron app (same desktop id, so pins/search keep working)
# The packaged ds5-bridge-companion stays installed: udev rules, AudioHelper
# and firmware files come from /opt/DS5 Bridge/resources.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
prefix="$(dirname "$here")"
node="$(command -v node)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

cd "$here"
[ -d node_modules ] || npm install --no-audit --no-fund
npm run -s build
if [ ! -f "$prefix/companion/dist/main/preload.js" ]; then
  (cd "$prefix/companion" && npm ci --no-audit --no-fund && npx tsc -p tsconfig.main.json && npx vite build)
fi

mkdir -p "$units" "$data/dbus-1/services" "$data/applications"
sed "s|@NODE@|$node|; s|@PREFIX@|$prefix|" data/ds5-bridged.service.in > "$units/ds5-bridged.service"
cp data/io.github.ds5bridge.Daemon.service "$data/dbus-1/services/"
sed "s|@PREFIX@|$prefix|" data/ds5-bridge.desktop.in > "$data/applications/ds5-bridge.desktop"

# The old Electron app must not run next to the daemon (both would drive the bridge).
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/ds5-bridge.desktop"

systemctl --user daemon-reload
systemctl --user enable --now ds5-bridged.service
update-desktop-database "$data/applications" 2>/dev/null || true
echo "ds5-bridged: $(systemctl --user is-active ds5-bridged.service)"

# Quick Settings tile (GNOME Shell extension)
uuid=ds5-bridge@matheus
ext="$data/gnome-shell/extensions/$uuid"
rm -rf "$ext" && mkdir -p "$ext" && cp shell-extension/* "$ext/"
gnome-extensions enable "$uuid" 2>/dev/null || {
  cur=$(gsettings get org.gnome.shell enabled-extensions)
  case "$cur" in *"$uuid"*) ;; *)
    gsettings set org.gnome.shell enabled-extensions \
      "$(python3 -c "import ast,sys; l=ast.literal_eval(sys.argv[1].replace('@as ','')); l.append(sys.argv[2]); print(l)" "$cur" "$uuid")";;
  esac
  echo "Quick Settings tile: log out and back in once to load it"
}
