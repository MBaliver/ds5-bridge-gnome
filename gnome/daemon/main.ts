// ds5-bridged: the upstream DS5 Bridge companion backend (BridgeService and
// friends, compiled unmodified from companion/src/main) running headless on
// plain Node, exposed on the session bus. It replaces upstream's Electron
// main.ts; every UI (legacy Electron, GTK, Shell extension) is a client.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import * as dbus from 'dbus-next';
import { BootloaderAuthorizationStore } from '../../companion/src/main/bootloader-authorization-store';
import { BridgeService, type BridgeToast } from '../../companion/src/main/bridge-service';
import {
  PICO_UNIVERSAL_FLASH_NUKE_FILE,
  PICO_UNIVERSAL_FLASH_NUKE_SHA256_FILE,
  flashPicoFirmwareUf2,
  mountPicoBootloaderDrive,
  nukePicoFlash
} from '../../companion/src/main/pico-firmware-updater';
import { SettingsStore } from '../../companion/src/main/settings-store';
import type { BridgeSnapshot, PicoFirmwareAction, PicoFirmwareActionResult } from '../../companion/src/shared/types';
import { CUSTOM_CHANNELS, GENERIC_METHODS, UPSTREAM_VERSION } from '../generated/upstream-ipc';
import { BUS_NAME, DAEMON_CHANNELS, ERROR_NAME, INTERFACE, OBJECT_PATH, decode, encode } from '../shared/wire';
import { HapticsMix, MIX_SINK_DESCRIPTION, MIX_SINK_NAME, type MixApp } from './haptics-mix';
import { KeyringProtection } from './keyring-protection';
import { startOrphanReaper } from './orphan-reaper';

const APP_NAME = 'DS5 Bridge';
const SYSTEMD_UNIT = 'ds5-bridged.service';

// ---------------------------------------------------------------- environment

// Same directory the Electron app uses, so settings and profiles carry over.
const configHome = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config');
const userDataPath = path.join(configHome, APP_NAME);

// Upstream finds the AudioHelper and firmware files under Electron's
// process.resourcesPath. Point it at our resources directory.
function resolveResourcesPath(): string {
  const candidates = [
    process.env.DS5_BRIDGE_RESOURCES,
    path.resolve(__dirname, '..', '..', '..', 'resources'),
    '/usr/lib/ds5-bridge-gnome/resources',
    '/opt/DS5 Bridge/resources'
  ].filter((c): c is string => Boolean(c));
  const found = candidates.find((c) => fs.existsSync(path.join(c, 'native', 'AudioHelper')));
  if (!found) {
    throw new Error(`No resources directory with native/AudioHelper found (tried: ${candidates.join(', ')}). Set DS5_BRIDGE_RESOURCES.`);
  }
  return found;
}
const resourcesPath = resolveResourcesPath();
process.resourcesPath = resourcesPath;

// ----------------------------------------------------------------- services

const settingsStore = new SettingsStore(userDataPath);
const service = new BridgeService(
  settingsStore,
  new BootloaderAuthorizationStore(userDataPath, new KeyringProtection())
);

// Upstream bug: bridge-service's normalizeAudioReactiveHapticsSource turns every
// `output-device` source into 'system-audio' (settings-store and audio-helper support it).
// Any config change (even Strength) would also wipe a saved one. Restore it afterwards.
{
  type Svc = {
    setAudioReactiveHapticsConfig(c: Record<string, unknown>): Promise<BridgeSnapshot>;
    snapshot: BridgeSnapshot;
    updateSystemAudioHapticsEngine(): Promise<void>;
    emitSnapshot(): void;
  };
  const svc = service as unknown as Svc;
  const original = svc.setAudioReactiveHapticsConfig.bind(service);
  const isDevice = (s: unknown) => typeof s === 'object' && s !== null && (s as { kind?: string }).kind === 'output-device';
  svc.setAudioReactiveHapticsConfig = async (config) => {
    const wanted = 'source' in config ? config.source : settingsStore.get().audioReactiveHapticsSource;
    if (!isDevice(wanted)) return original(config);
    // Upstream's own snapshot briefly says 'system-audio'; keep the mix watchdog quiet meanwhile.
    const wasSwitching = mixSwitching;
    mixSwitching = true;
    try {
      await original(config);
    } finally {
      mixSwitching = wasSwitching;
    }
    if (isDevice(settingsStore.get().audioReactiveHapticsSource)) return service.getSnapshot();
    svc.snapshot.settings = settingsStore.update({ audioReactiveHapticsSource: wanted } as never);
    await svc.updateSystemAudioHapticsEngine();
    svc.emitSnapshot();
    return service.getSnapshot();
  };
}

let firmwareActionsRunning = 0;

// ------------------------------------------------- GNOME-layer settings

const gnomeSettingsPath = path.join(userDataPath, 'gnome-daemon.json');
type GnomeSettings = { hapticsMix: { enabled: boolean; excluded: MixApp[] } };
// The apps the user named: voice chat, music and browsers. Games are everything else.
const DEFAULT_EXCLUDED: MixApp[] = [
  ['discord', 'Discord'], ['vesktop', 'Vesktop'], ['spotify', 'Spotify'], ['firefox', 'Firefox'],
  ['chrome', 'Google Chrome'], ['chromium', 'Chromium'], ['brave', 'Brave'], ['zen', 'Zen Browser'],
  ['librewolf', 'LibreWolf'], ['vivaldi-bin', 'Vivaldi'], ['msedge', 'Microsoft Edge']
].map(([key, name]) => ({ key, name }));

function readGnomeSettings(): GnomeSettings {
  try {
    const parsed = JSON.parse(fs.readFileSync(gnomeSettingsPath, 'utf8')) as Partial<GnomeSettings>;
    return { hapticsMix: { enabled: Boolean(parsed.hapticsMix?.enabled), excluded: parsed.hapticsMix?.excluded ?? DEFAULT_EXCLUDED } };
  } catch {
    return { hapticsMix: { enabled: false, excluded: DEFAULT_EXCLUDED } };
  }
}

function writeGnomeSettings(next: GnomeSettings): void {
  fs.mkdirSync(path.dirname(gnomeSettingsPath), { recursive: true });
  fs.writeFileSync(`${gnomeSettingsPath}.tmp`, JSON.stringify(next, null, 2));
  fs.renameSync(`${gnomeSettingsPath}.tmp`, gnomeSettingsPath);
}

let gnomeSettings = readGnomeSettings();
const hapticsMix = new HapticsMix();
const MIX_SOURCE = { kind: 'output-device' as const, deviceName: MIX_SINK_NAME, displayName: MIX_SINK_DESCRIPTION };

function sourceIsMix(snapshot: BridgeSnapshot): boolean {
  const source = snapshot.settings.audioReactiveHapticsSource as unknown;
  return typeof source === 'object' && source !== null
    && (source as { kind?: string; deviceName?: string }).kind === 'output-device'
    && (source as { deviceName?: string }).deviceName === MIX_SINK_NAME;
}

let mixSwitching = false;

async function setHapticsMix(enabled: boolean, excluded?: MixApp[]): Promise<unknown> {
  mixSwitching = true;
  try {
    return await applyHapticsMix(enabled, excluded);
  } finally {
    mixSwitching = false;
  }
}

async function applyHapticsMix(enabled: boolean, excluded?: MixApp[]): Promise<unknown> {
  const clean = (excluded ?? gnomeSettings.hapticsMix.excluded)
    .filter((app) => app && typeof app.key === 'string' && app.key.trim())
    .map((app) => ({ key: app.key.trim().toLowerCase(), name: String(app.name || app.key) }));
  gnomeSettings = { hapticsMix: { enabled, excluded: clean } };
  writeGnomeSettings(gnomeSettings);
  if (enabled) {
    await hapticsMix.start(clean);
    if (!sourceIsMix(service.getSnapshot())) {
      await service.setAudioReactiveHapticsConfig({ source: MIX_SOURCE });
    }
  } else {
    await hapticsMix.stop();
    if (sourceIsMix(service.getSnapshot())) {
      await service.setAudioReactiveHapticsConfig({ source: 'system-audio' });
    }
  }
  return getHapticsMix();
}

async function getHapticsMix(): Promise<unknown> {
  hapticsMix.setExcluded(gnomeSettings.hapticsMix.excluded);
  const streams = hapticsMix.running ? hapticsMix.streams : await hapticsMix.listStreams().catch(() => []);
  return { ...gnomeSettings.hapticsMix, running: hapticsMix.running, sinkName: MIX_SINK_NAME, streams };
}

function firmwareOptions(includeNuke = false) {
  return {
    enterBootloader: () => service.mountPicoBootloader(),
    ...(includeNuke
      ? {
          nukeUf2Path: path.join(resourcesPath, 'firmware', PICO_UNIVERSAL_FLASH_NUKE_FILE),
          nukeUf2Sha256Path: path.join(resourcesPath, 'firmware', PICO_UNIVERSAL_FLASH_NUKE_SHA256_FILE)
        }
      : {})
  };
}

// Mirrors upstream main.ts runPicoFirmwareIpcAction / picoFirmwareErrorMessage.
async function runFirmwareAction(
  action: PicoFirmwareAction,
  task: () => Promise<PicoFirmwareActionResult>
): Promise<PicoFirmwareActionResult> {
  firmwareActionsRunning += 1;
  try {
    return await task();
  } catch (error) {
    const raw = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
    const cleaned = raw.replace(/^Error:\s*/i, '').trim();
    const message = /No companion bridge is connected/i.test(cleaned)
      ? 'No companion bridge is connected. Connect the companion bridge, then try again.'
      : cleaned || 'Pico firmware action failed.';
    return { ok: false, action, message };
  } finally {
    firmwareActionsRunning -= 1;
  }
}

// Launch at startup = the systemd user unit is enabled (replaces upstream's
// ~/.config/autostart .desktop entry, which would start the whole Electron UI).
function applyLaunchAtStartup(enabled: boolean): void {
  const result = spawnSync('systemctl', ['--user', enabled ? 'enable' : 'disable', SYSTEMD_UNIT], { encoding: 'utf8' });
  if (result.status !== 0) {
    console.warn(`[autostart] systemctl ${enabled ? 'enable' : 'disable'} failed: ${(result.stderr || '').trim()}`);
  }
}

// ------------------------------------------------------------ IPC dispatch

type Handler = (...args: any[]) => unknown;

// Hand-written halves of upstream's custom handlers (see upstream-ipc.lock.json).
// UI-only behaviour (window scale, tester window, file pickers, icons) lives in clients.
const OVERRIDES: Record<string, Handler> = {
  'bridge:getStatus': () => service.getSnapshot(),
  'app:getVersion': () => UPSTREAM_VERSION,
  // Clients add app icons (a UI concern) on top of this.
  'bridge:listAudioHapticsSessions': () => service.listAudioHapticsSessions(),
  'bridge:setUiScalePercent': (value) => service.setUiScalePercent(value),
  'bridge:setLaunchAtStartupEnabled': (value) => {
    const snapshot = service.setLaunchAtStartupEnabled(Boolean(value));
    applyLaunchAtStartup(snapshot.settings.launchAtStartupEnabled);
    return snapshot;
  },
  'bridge:restoreDefaults': async () => {
    const snapshot = await service.restoreDefaults();
    applyLaunchAtStartup(snapshot.settings.launchAtStartupEnabled);
    return snapshot;
  },
  'bridge:getDiagnostics': () => service.getSnapshot().diagnostics,
  'bridge:mountPicoBootloader': () => runFirmwareAction('mount', () => mountPicoBootloaderDrive(firmwareOptions())),
  [DAEMON_CHANNELS.flashPicoFirmwareFile]: (filePath: string) => runFirmwareAction(
    'flash',
    () => flashPicoFirmwareUf2(String(filePath), firmwareOptions())
  ),
  [DAEMON_CHANNELS.nukePicoFlashConfirmed]: () => runFirmwareAction('nuke', () => nukePicoFlash(firmwareOptions(true))),
  [DAEMON_CHANNELS.firmwareActionRunning]: () => firmwareActionsRunning > 0,
  [DAEMON_CHANNELS.getHapticsMix]: () => getHapticsMix(),
  [DAEMON_CHANNELS.setHapticsMix]: (enabled: boolean, excluded?: MixApp[]) => setHapticsMix(Boolean(enabled), excluded)
};

// Custom upstream channels a client must implement (UI-side). The daemon refuses them.
const CLIENT_ONLY = new Set([
  'bridge:flashPicoFirmware', 'bridge:nukePicoFlash', 'bridge:openTesterWindow',
  'window:minimize', 'window:toggleMaximize', 'window:isMaximized', 'window:hide', 'window:openExternal'
]);

const missing = CUSTOM_CHANNELS.filter((c) => !OVERRIDES[c] && !CLIENT_ONLY.has(c));
if (missing.length) {
  // A new custom upstream handler nobody implemented: refuse to start silently broken.
  console.error(`[ds5-bridged] custom upstream channels without implementation: ${missing.join(', ')}`);
  console.error('Run `npm run check-upstream` in gnome/.');
  process.exit(2);
}

function resolveHandler(channel: string): Handler {
  const override = OVERRIDES[channel];
  if (override) return override;
  // Only methods upstream itself exposes through a generic handler.
  const method = GENERIC_METHODS[channel];
  const fn = method ? (service as unknown as Record<string, unknown>)[method] : undefined;
  if (typeof fn === 'function') return (fn as Handler).bind(service);
  if (CLIENT_ONLY.has(channel)) throw new dbus.DBusError(ERROR_NAME, `${channel} is handled by the client UI`);
  throw new dbus.DBusError(ERROR_NAME, `Unknown channel ${channel}`);
}

// ------------------------------------------------------------------ D-Bus

const { Interface, ACCESS_READ } = dbus.interface;

type Summary = {
  State: string;
  Connected: boolean;
  ControllerName: string;
  BatteryPercent: number;
  Charging: boolean;
};

function controllerName(type: string | undefined): string {
  if (type === 'dualsense-edge') return 'DualSense Edge';
  if (type === 'dualsense') return 'DualSense';
  return 'Controller';
}

// Same rule as upstream main.ts isChargingPowerState.
function summarize(snapshot: BridgeSnapshot): Summary {
  const status = snapshot.status;
  return {
    State: snapshot.state,
    Connected: Boolean(status?.controllerConnected),
    ControllerName: status?.controllerConnected ? controllerName(status.controllerType) : '',
    BatteryPercent: status?.controllerConnected && status.batteryPercent !== null ? status.batteryPercent : -1,
    Charging: status?.rawPowerState === 0x01 || status?.rawPowerState === 0x02
  };
}

class DaemonInterface extends Interface {
  private summary: Summary = summarize(service.getSnapshot());

  get State(): string { return this.summary.State; }
  get Connected(): boolean { return this.summary.Connected; }
  get ControllerName(): string { return this.summary.ControllerName; }
  get BatteryPercent(): number { return this.summary.BatteryPercent; }
  get Charging(): boolean { return this.summary.Charging; }
  get UpstreamVersion(): string { return UPSTREAM_VERSION; }

  async Call(channel: string, argsJson: string): Promise<string> {
    const handler = resolveHandler(channel);
    const args = decode<unknown[]>(argsJson) ?? [];
    if (!Array.isArray(args)) throw new dbus.DBusError(ERROR_NAME, 'argsJson must be a JSON array');
    try {
      return encode(await handler(...args));
    } catch (error) {
      if (error instanceof dbus.DBusError) throw error;
      throw new dbus.DBusError(ERROR_NAME, error instanceof Error ? error.message : String(error));
    }
  }

  Quit(): void {
    void shutdown('D-Bus Quit');
  }

  // Signals: calling these emits them.
  Snapshot(json: string): string { return json; }
  Toast(title: string, body: string): string[] { return [title, body]; }

  updateSummary(snapshot: BridgeSnapshot): void {
    const next = summarize(snapshot);
    const changed: Record<string, unknown> = {};
    for (const key of Object.keys(next) as Array<keyof Summary>) {
      if (next[key] !== this.summary[key]) changed[key] = next[key];
    }
    this.summary = next;
    if (Object.keys(changed).length) Interface.emitPropertiesChanged(this, changed, []);
  }
}

DaemonInterface.configureMembers({
  properties: {
    State: { signature: 's', access: ACCESS_READ },
    Connected: { signature: 'b', access: ACCESS_READ },
    ControllerName: { signature: 's', access: ACCESS_READ },
    BatteryPercent: { signature: 'i', access: ACCESS_READ },
    Charging: { signature: 'b', access: ACCESS_READ },
    UpstreamVersion: { signature: 's', access: ACCESS_READ }
  },
  methods: {
    Call: { inSignature: 'ss', outSignature: 's' },
    Quit: { inSignature: '', outSignature: '' }
  },
  signals: {
    Snapshot: { signature: 's' },
    Toast: { signature: 'ss' }
  }
});

const bus = dbus.sessionBus();
const iface = new DaemonInterface(INTERFACE);

async function notify(toast: BridgeToast): Promise<void> {
  try {
    const proxy = await bus.getProxyObject('org.freedesktop.Notifications', '/org/freedesktop/Notifications');
    const notifications = proxy.getInterface('org.freedesktop.Notifications');
    await notifications.Notify(
      APP_NAME, 0, 'ds5-bridge', toast.title, toast.body, [],
      { 'desktop-entry': new dbus.Variant('s', 'ds5-bridge') }, -1
    );
  } catch (error) {
    console.warn('[notify] failed:', (error as Error).message);
  }
}

// ---------------------------------------------------------------- lifecycle

let stopping = false;
async function shutdown(reason: string): Promise<void> {
  if (stopping) return;
  stopping = true;
  console.log(`[ds5-bridged] stopping (${reason})`);
  try {
    await hapticsMix.stop();
    await service.stop();
  } finally {
    bus.disconnect();
    process.exit(0);
  }
}

async function main(): Promise<void> {
  const reply = await bus.requestName(BUS_NAME, dbus.NameFlag.DO_NOT_QUEUE);
  if (reply !== dbus.RequestNameReply.PRIMARY_OWNER) {
    console.error(`[ds5-bridged] ${BUS_NAME} is already owned; another daemon is running.`);
    process.exit(1);
  }
  bus.export(OBJECT_PATH, iface);

  let lastSnapshotJson = '';
  service.on('snapshot', (snapshot: BridgeSnapshot) => {
    // Another client picked a different source: the mix has nothing to feed any more.
    if (!mixSwitching && gnomeSettings.hapticsMix.enabled && hapticsMix.running && !sourceIsMix(snapshot)) {
      void setHapticsMix(false);
    }
    iface.updateSummary(snapshot);
    const json = encode(snapshot);
    if (json === lastSnapshotJson) return;
    lastSnapshotJson = json;
    iface.Snapshot(json);
  });
  service.on('toast', (toast: BridgeToast) => {
    iface.Toast(toast.title, toast.body);
    void notify(toast);
  });

  process.on('SIGTERM', () => void shutdown('SIGTERM'));
  process.on('SIGINT', () => void shutdown('SIGINT'));

  service.start();
  startOrphanReaper();
  if (gnomeSettings.hapticsMix.enabled) {
    setHapticsMix(true).catch((error) => console.warn('[haptics-mix] start failed:', (error as Error).message));
  }
  process.on('exit', () => hapticsMix.stopSync());
  console.log(`[ds5-bridged] upstream ${UPSTREAM_VERSION} on ${BUS_NAME}; resources=${resourcesPath}; config=${userDataPath}`);
}

main().catch((error) => {
  console.error('[ds5-bridged] fatal:', error);
  process.exit(1);
});
