// Legacy UI client: the upstream React renderer + upstream preload.ts, both
// unmodified, in an Electron window whose IPC is forwarded to ds5-bridged.
//
// This keeps every upstream screen available while the GTK app catches up.
// Closing the window only closes the UI: the daemon keeps the bridge running.
import { BrowserWindow, app, dialog, ipcMain, nativeImage, screen, shell } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as dbus from 'dbus-next';
import type { AudioHapticsSession, BridgeSnapshot, PicoFirmwareActionResult } from '../../companion/src/shared/types';
import { INVOKE_CHANNELS } from '../generated/upstream-ipc';
import { BUS_NAME, DAEMON_CHANNELS, INTERFACE, OBJECT_PATH, decode, encode } from '../shared/wire';

const APP_NAME = 'DS5 Bridge';
const BASE_WINDOW_WIDTH = 1120;
const BASE_WINDOW_HEIGHT = 630;

// Upstream build output (companion: `tsc -p tsconfig.main.json && vite build`).
const uiDir = process.env.DS5_BRIDGE_UI_DIR
  ?? path.resolve(__dirname, '..', '..', '..', '..', 'companion', 'dist');
const preloadPath = path.join(uiDir, 'main', 'preload.js');
const rendererIndexPath = path.join(uiDir, 'renderer', 'index.html');
const testerIndexPath = path.join(uiDir, 'renderer', 'tester.html');
const iconPath = process.env.DS5_BRIDGE_ICON
  ?? path.resolve(__dirname, '..', '..', '..', '..', 'assets', 'controllers', 'ds5-bridge_mark.png');

// Same identity tweaks as upstream main.ts (desktop-file match, shared userData).
app.setPath('userData', path.join(app.getPath('appData'), APP_NAME));
app.setName('ds5-bridge');
app.commandLine.appendSwitch('class', 'ds5-bridge');

if (!app.requestSingleInstanceLock()) {
  app.quit();
}

let mainWindow: BrowserWindow | null = null;
let testerWindow: BrowserWindow | null = null;
let daemon: dbus.ClientInterface | null = null;

// ------------------------------------------------------------------ daemon

async function connectDaemon(): Promise<dbus.ClientInterface> {
  const bus = dbus.sessionBus();
  // getProxyObject triggers D-Bus activation when the service file is installed.
  const proxy = await bus.getProxyObject(BUS_NAME, OBJECT_PATH);
  return proxy.getInterface(INTERFACE);
}

async function call<T = unknown>(channel: string, args: unknown[] = []): Promise<T> {
  if (!daemon) throw new Error('DS5 Bridge daemon is not connected.');
  try {
    return decode<T>(await daemon.Call(channel, encode(args)));
  } catch (error) {
    // Surface the daemon's message, not the D-Bus envelope.
    const text = (error as { text?: string }).text ?? (error as Error).message;
    throw new Error(text);
  }
}

// ------------------------------------------------------------ window scale
// Copied from upstream main.ts: the fixed-aspect UI zooms to fill the window.

function scaledWindowSize(uiScalePercent: number) {
  const scale = uiScalePercent / 100;
  return { width: Math.round(BASE_WINDOW_WIDTH * scale), height: Math.round(BASE_WINDOW_HEIGHT * scale) };
}

function fitZoomForBounds(width: number, height: number): number {
  return Math.max(0.25, Math.min(width / BASE_WINDOW_WIDTH, height / BASE_WINDOW_HEIGHT));
}

function applyWindowScale(window: BrowserWindow, uiScalePercent: number): void {
  const { width, height } = scaledWindowSize(uiScalePercent);
  const bounds = window.getBounds();
  const workArea = screen.getDisplayMatching(bounds).workArea;
  const cx = bounds.x + bounds.width / 2;
  const cy = bounds.y + bounds.height / 2;
  const x = Math.round(Math.max(workArea.x, Math.min(cx - width / 2, workArea.x + workArea.width - width)));
  const y = Math.round(Math.max(workArea.y, Math.min(cy - height / 2, workArea.y + workArea.height - height)));
  window.setBounds({ x, y, width, height }, false);
  window.webContents.setZoomFactor(fitZoomForBounds(width, height));
}

function refitZoom(window: BrowserWindow | null): void {
  if (!window || window.isDestroyed()) return;
  const { width, height } = window.getBounds();
  window.webContents.setZoomFactor(fitZoomForBounds(width, height));
}

// ----------------------------------------------------------------- windows

function isAllowedExternalUrl(url: string): boolean {
  return /^https:\/\/github\.com\/(djanice1980|SundayMoments)\/DS5_Bridge\/?$/i.test(url);
}

function sameFile(url: string, filePath: string): boolean {
  try {
    return path.normalize(fileURLToPath(url)) === path.normalize(filePath);
  } catch {
    return false;
  }
}

function lockDown(window: BrowserWindow, indexPath: string): void {
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedExternalUrl(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (!sameFile(url, indexPath)) event.preventDefault();
  });
}

const webPreferences = { preload: preloadPath, contextIsolation: true, nodeIntegration: false, sandbox: true };

function createMainWindow(uiScalePercent: number): BrowserWindow {
  const { width, height } = scaledWindowSize(uiScalePercent);
  const window = new BrowserWindow({
    width,
    height,
    minWidth: Math.round(BASE_WINDOW_WIDTH / 2),
    minHeight: Math.round(BASE_WINDOW_HEIGHT / 2),
    show: false,
    title: APP_NAME,
    frame: false,
    backgroundColor: '#0b1017',
    icon: nativeImage.createFromPath(iconPath),
    webPreferences
  });
  window.webContents.session.setPermissionRequestHandler((contents, permission, callback) => {
    callback(contents === window.webContents && (permission === 'media' || permission === 'speaker-selection'));
  });
  lockDown(window, rendererIndexPath);
  window.on('resize', () => refitZoom(window));
  window.on('show', () => setTimeout(() => refitZoom(window), 0));
  const sendMaximized = () => window.webContents.send('window:maximizedChanged', window.isMaximized());
  window.on('maximize', sendMaximized);
  window.on('unmaximize', sendMaximized);
  window.once('ready-to-show', () => {
    window.show();
    window.focus();
  });
  window.webContents.once('did-finish-load', () => refitZoom(window));
  window.on('closed', () => {
    mainWindow = null;
    app.quit();
  });
  void window.loadFile(rendererIndexPath);
  if (process.env.DS5_DEBUG === '1') window.webContents.openDevTools({ mode: 'detach' });
  return window;
}

function openTesterWindow(): void {
  if (testerWindow && !testerWindow.isDestroyed()) {
    if (testerWindow.isMinimized()) testerWindow.restore();
    testerWindow.focus();
    return;
  }
  const window = new BrowserWindow({
    width: 1180,
    height: 900,
    minWidth: 900,
    minHeight: 640,
    show: false,
    title: 'DS5 Bridge Tester',
    backgroundColor: '#0b1017',
    icon: nativeImage.createFromPath(iconPath),
    webPreferences
  });
  window.setMenuBarVisibility(false);
  lockDown(window, testerIndexPath);
  window.on('closed', () => { testerWindow = null; });
  window.once('ready-to-show', () => window.show());
  void window.loadFile(testerIndexPath);
  testerWindow = window;
}

// ------------------------------------------------------ client-side halves
// UI parts of upstream's custom handlers (see gnome/upstream-ipc.lock.json).

async function flashPicoFirmware(): Promise<PicoFirmwareActionResult> {
  const options: Electron.OpenDialogOptions = {
    title: 'Choose Pico firmware UF2',
    properties: ['openFile'],
    filters: [{ name: 'UF2 firmware', extensions: ['uf2'] }, { name: 'All files', extensions: ['*'] }]
  };
  const result = mainWindow ? await dialog.showOpenDialog(mainWindow, options) : await dialog.showOpenDialog(options);
  const sourcePath = result.canceled ? null : result.filePaths[0] ?? null;
  if (!sourcePath) return { ok: false, action: 'flash', cancelled: true, message: 'Firmware flash cancelled.' };
  return call(DAEMON_CHANNELS.flashPicoFirmwareFile, [sourcePath]);
}

async function nukePicoFlash(): Promise<PicoFirmwareActionResult> {
  const options: Electron.MessageBoxOptions = {
    type: 'warning',
    title: 'Nuke Pico flash?',
    message: 'Nuke Pico flash?',
    detail: 'This will copy the bundled Pico Universal Flash Nuke UF2 to the mounted Pico bootloader drive and erase the Pico flash.\n\nThe bridge will not work again until you flash the DS5 Bridge firmware back onto the Pico. Use this only when recovering from a bad or stuck firmware install.',
    buttons: ['Nuke Pico', 'Cancel'],
    defaultId: 1,
    cancelId: 1,
    noLink: true
  };
  const result = mainWindow ? await dialog.showMessageBox(mainWindow, options) : await dialog.showMessageBox(options);
  if (result.response !== 0) return { ok: false, action: 'nuke', cancelled: true, message: 'Pico flash nuke cancelled.' };
  return call(DAEMON_CHANNELS.nukePicoFlashConfirmed);
}

const iconCache = new Map<string, string | null>();
async function sessionIcon(session: AudioHapticsSession): Promise<string | null> {
  const key = session.iconPath || session.processPath || session.executableName || null;
  if (key && iconCache.has(key)) return iconCache.get(key) ?? null;
  let value: string | null = session.iconDataUrl ?? null;
  if (!value && session.iconPath && fs.existsSync(session.iconPath)) {
    const image = nativeImage.createFromPath(session.iconPath);
    if (!image.isEmpty()) value = image.resize({ width: 32, height: 32 }).toDataURL();
  }
  if (!value && session.processPath && fs.existsSync(session.processPath)) {
    try {
      const image = await app.getFileIcon(session.processPath, { size: 'normal' });
      if (!image.isEmpty()) value = image.resize({ width: 32, height: 32 }).toDataURL();
    } catch { /* no icon */ }
  }
  if (key) iconCache.set(key, value);
  return value;
}

type Local = (...args: any[]) => unknown;
const LOCAL: Record<string, Local> = {
  'bridge:listAudioHapticsSessions': async () => {
    const sessions = await call<AudioHapticsSession[]>('bridge:listAudioHapticsSessions');
    return Promise.all(sessions.map(async (s) => ({ ...s, iconDataUrl: await sessionIcon(s) })));
  },
  'bridge:setUiScalePercent': async (value: number) => {
    const snapshot = await call<BridgeSnapshot>('bridge:setUiScalePercent', [value]);
    if (mainWindow) applyWindowScale(mainWindow, snapshot.settings.uiScalePercent);
    return snapshot;
  },
  'bridge:restoreDefaults': async () => {
    const snapshot = await call<BridgeSnapshot>('bridge:restoreDefaults');
    if (mainWindow) applyWindowScale(mainWindow, snapshot.settings.uiScalePercent);
    return snapshot;
  },
  'bridge:flashPicoFirmware': flashPicoFirmware,
  'bridge:nukePicoFlash': nukePicoFlash,
  'bridge:openTesterWindow': () => openTesterWindow(),
  'window:minimize': () => mainWindow?.minimize(),
  'window:toggleMaximize': () => {
    if (!mainWindow) return;
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  },
  'window:isMaximized': () => Boolean(mainWindow?.isMaximized()),
  // Upstream hides to the tray. Here the daemon is the background part, so the UI just closes.
  'window:hide': () => mainWindow?.close(),
  'window:openExternal': (url: string) => {
    if (isAllowedExternalUrl(url)) void shell.openExternal(url);
  }
};

function registerIpc(): void {
  for (const channel of INVOKE_CHANNELS) {
    const local = LOCAL[channel];
    ipcMain.handle(channel, (_event, ...args: unknown[]) => (local ? local(...args) : call(channel, args)));
  }
}

// --------------------------------------------------------------- lifecycle

app.on('second-instance', () => {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
});

app.on('window-all-closed', () => app.quit());

app.whenReady().then(async () => {
  try {
    daemon = await connectDaemon();
  } catch (error) {
    dialog.showErrorBox(APP_NAME, `Could not reach the DS5 Bridge service (${BUS_NAME}).\n\n${(error as Error).message}\n\nStart it with: systemctl --user start ds5-bridged`);
    app.quit();
    return;
  }
  daemon.on('Snapshot', (json: string) => {
    const snapshot = decode<BridgeSnapshot>(json);
    for (const window of [mainWindow, testerWindow]) {
      if (window && !window.isDestroyed()) window.webContents.send('bridge:snapshot', snapshot);
    }
  });
  registerIpc();
  const snapshot = await call<BridgeSnapshot>('bridge:getStatus');
  mainWindow = createMainWindow(snapshot.settings.uiScalePercent);
});
