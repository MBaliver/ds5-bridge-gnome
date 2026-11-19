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
| `app/` | **DS5 Bridge** GTK4/libadwaita app (Python), laid out like GNOME Settings. It covers controller (with upstream's DualSense art), profiles, devices with per-controller profile and remapping links, audio, haptics, triggers, lighting, buttons (including mute as a keyboard key), button remapping (with upstream's PS5 glyphs, recolored to the theme), chords, a Trigger Lab (all seven native effect types, per-zone sliders, the exact bytes sent, presets, linked/split), bridges (pick, rename, audio/haptics output), the flash erase, a live input tester window, per-app/per-output haptics sources, stick calibration (centre and range with a sweep coverage view, verified step by step against the controller's replies, input held from games, and a permanent mode behind a typed confirmation) and system. Screens it does not have yet open the classic UI. `DS5_GTK_SNAPSHOT=/prefix` renders every page to PNG. |
| `shell-extension/` | `ds5-bridge@matheus`: a **DualSense** tile in Quick Settings (battery, profiles, emulated controller, haptics/mic/light bar, turn off) and a top-bar icon while connected. |
| `client/` | The upstream React UI and `preload.ts`, unmodified, in an Electron window whose IPC is forwarded to the daemon. A fallback for every screen the GTK app doesn't have yet. |
| `shared/wire.ts` | D-Bus names and the JSON codec (keeps `undefined`, like Electron's structured clone). |
| `scripts/` | Upstream parser, channel generator, sync check, `mock-daemon.mjs` (fake service for UI work). |
| `dev/` | `nested-test.sh` runs the extension in an isolated nested GNOME Shell against the mock and saves screenshots. |
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

This enables `ds5-bridged.service` (systemd user unit, also D-Bus activatable). It installs `io.github.ds5bridge.App.desktop` (the GTK app) and hides the packaged Electron entry behind a `ds5-bridge.desktop` override that runs the classic client. It also installs and enables the Quick Settings extension, which needs one logout/login the first time. The packaged `ds5-bridge-companion` stays installed: it provides udev rules, the AudioHelper binary and the firmware files (`/opt/DS5 Bridge/resources`, or set `DS5_BRIDGE_RESOURCES`). The old Electron app must not run at the same time as the daemon.

Undo: `systemctl --user disable --now ds5-bridged`, then remove `~/.config/systemd/user/ds5-bridged.service`, `~/.local/share/dbus-1/services/io.github.ds5bridge.Daemon.service` and `~/.local/share/applications/ds5-bridge.desktop`.

## GNOME-layer features (not in upstream)

- **Haptics from all apps except…** (`daemon/haptics-mix.ts`): audio-reactive haptics fed by every app except the ones you exclude (voice chat, music, browsers), so whatever game is running drives them automatically. It creates a null sink "DS5 Haptics Mix" and fans a copy of each non-excluded app stream into it with `pw-link`. Apps keep playing to their normal output. The link set is reconciled from `pw-dump` every 1.5 s, and the haptics source points at the sink, which upstream already captures as an output device. Settings live in `~/.config/DS5 Bridge/gnome-daemon.json`. Daemon channels: `daemon:getHapticsMix`, `daemon:setHapticsMix(enabled, excluded)`.
- **Orphaned audio streams reaper** (`daemon/orphan-reaper.ts`): if upstream's AudioHelper dies without its own shutdown path (SIGKILL, crash, or the controller powering off so the bridge re-enumerates as 0x0ce7), its `pw-play`/`pw-record` haptics pair is orphaned and keeps a stream on the controller's vanished ALSA sink. PipeWire then retries that dead device until it runs out of file descriptors and no app can play audio. Every 5 s the daemon stops any `pw-play`/`pw-record`/`pw-cat` in its own unit cgroup whose parent is no longer in that cgroup. The haptics-mix PipeWire commands also time out after 5 s.

## Differences from upstream behaviour

- Launch at startup enables or disables the systemd unit instead of writing `~/.config/autostart`.
- No tray icon: status lives in the Quick Settings tile. The classic UI is still under Main Menu → Classic Interface.
- Bootloader authorization keys are sealed with a master key in the GNOME keyring (libsecret) instead of Electron `safeStorage`.

## Known limitations

- The AudioHelper (.NET) comes from the installed package, not from this checkout. If the package and the checkout drift to different versions, the TS ↔ helper protocol may not match. Building it here needs the .NET 9 SDK (`npm run build:audio-helper:linux` in `companion/`).
