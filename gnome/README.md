# DS5 Bridge — GNOME layer

A GNOME-native frontend for [DS5 Bridge](https://github.com/djanice1980/DS5_Bridge)
that stays in sync with upstream. **Nothing under `companion/` is modified.**
All GNOME code lives in `gnome/`, so `git merge upstream/main` does not conflict.

```
 GTK app (planned)  ─┐
 Shell Quick Settings ├── D-Bus: io.github.ds5bridge.Daemon ──► ds5-bridged (Node)
 Legacy Electron UI ─┘   Call(channel, argsJson) / Snapshot / Toast   └ upstream BridgeService,
                                                                        SettingsStore, AudioHelper…
```

## Pieces

| Path | What |
|---|---|
| `daemon/` | `ds5-bridged`: upstream backend compiled as-is, run on plain Node, exported on the session bus. Replaces upstream's Electron `main.ts`. |
| `client/` | The upstream React UI and `preload.ts`, unmodified, in an Electron window whose IPC is forwarded to the daemon. A fallback for every screen the GTK app doesn't have yet. |
| `shared/wire.ts` | D-Bus names and the JSON codec (keeps `undefined`, like Electron's structured clone). |
| `scripts/` | Upstream parser, channel generator, sync check. |
| `upstream-ipc.lock.json` | Hashes of upstream's handwritten IPC handlers, used to detect changes. |

## D-Bus API (`io.github.ds5bridge.Daemon1` at `/io/github/ds5bridge/Daemon`)

- `Call(s channel, s argsJson) → s resultJson` takes any upstream channel (`bridge:setHapticsGain`, …) with the same arguments and result as upstream's renderer API (`window.bridge`).
- Signals: `Snapshot(s json)` (only when the snapshot changes) and `Toast(s title, s body)`. Toasts also become desktop notifications.
- Properties (with `PropertiesChanged`, for the Shell extension): `State`, `Connected`, `ControllerName`, `BatteryPercent` (-1 = unknown), `Charging`, `UpstreamVersion`.
- `Quit()`.
- Daemon-only channels: `daemon:flashPicoFirmwareFile(path)`, `daemon:nukePicoFlashConfirmed()`, `daemon:firmwareActionRunning()`. The client handles the file picker and the confirmation.

```sh
gdbus call --session --dest io.github.ds5bridge.Daemon --object-path /io/github/ds5bridge/Daemon \
  --method io.github.ds5bridge.Daemon1.Call bridge:setHapticsGain '[80]'
```

## Staying in sync with upstream

```sh
git fetch upstream && git merge upstream/main
cd gnome && npm run build && npm run check-upstream
```

- **Generic channels** (~85% of them, where upstream only calls `service.<channel>(…)`) work automatically. The channel list is regenerated from upstream's `main.ts` and `preload.ts` on every build.
- **Custom channels** (16 today): `check-upstream` fails if one is added, changed or removed, and prints the new upstream code. After porting the change into `daemon/main.ts` (`OVERRIDES`) or `client/main.ts` (`LOCAL`), run `npm run check-upstream -- --accept`.
- The daemon refuses to start if a custom upstream channel has no implementation.
- Changes to BridgeService's constructor or events also trip the check.

## Install (current user, from this checkout)

```sh
./gnome/install-user.sh
```

This enables `ds5-bridged.service` (systemd user unit, also D-Bus activatable) and overrides `ds5-bridge.desktop` so the launcher opens the client. The packaged `ds5-bridge-companion` stays installed: it provides udev rules, the AudioHelper binary and the firmware files (`/opt/DS5 Bridge/resources`, or set `DS5_BRIDGE_RESOURCES`). The old Electron app must not run at the same time as the daemon.

Undo: `systemctl --user disable --now ds5-bridged`, then remove `~/.config/systemd/user/ds5-bridged.service`, `~/.local/share/dbus-1/services/io.github.ds5bridge.Daemon.service` and `~/.local/share/applications/ds5-bridge.desktop`.

## Differences from upstream behaviour

- Launch at startup enables or disables the systemd unit instead of writing `~/.config/autostart`.
- No tray icon. Closing the window closes only the UI, and the bridge keeps running in the daemon. Battery and status will move to a GNOME Quick Settings tile.
- Bootloader authorization keys are sealed with a master key in the GNOME keyring (libsecret) instead of Electron `safeStorage`.

## Known limitations

- The AudioHelper (.NET) comes from the installed package, not from this checkout. If the package and the checkout drift to different versions, the TS ↔ helper protocol may not match. Building it here needs the .NET 9 SDK (`npm run build:audio-helper:linux` in `companion/`).
