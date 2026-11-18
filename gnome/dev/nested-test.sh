#!/bin/sh
# Runs the Quick Settings extension in a nested, isolated GNOME Shell against
# the mock daemon and saves screenshots to $1-*.png. Touches nothing in the
# real session: own D-Bus, own dconf (XDG_CONFIG_HOME), own extensions dir.
set -eu
here="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:?usage: nested-test.sh /path/prefix}"
tmp="$(mktemp -d)"
mkdir -p "$tmp/config" "$tmp/data/gnome-shell/extensions"
cp -r "$here/shell-extension" "$tmp/data/gnome-shell/extensions/ds5-bridge@matheus"
export XDG_CONFIG_HOME="$tmp/config" XDG_DATA_HOME="$tmp/data" DS5_BRIDGE_SELFTEST="$out"
dbus-run-session -- sh -c "
  gsettings set org.gnome.shell enabled-extensions \"['ds5-bridge@matheus']\"
  gsettings set org.gnome.shell welcome-dialog-last-shown-version '999'
  gsettings set org.gnome.desktop.interface color-scheme prefer-dark
  node '$here/scripts/mock-daemon.mjs' &
  sleep 1
  timeout 25 gnome-shell --devkit --virtual-monitor 1280x800 2>&1 | grep -iE 'ds5|JS ERROR|extension' || true
"
rm -rf "$tmp"
