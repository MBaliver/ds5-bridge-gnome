// D-Bus contract between ds5-bridged and its clients (legacy Electron UI, the
// GTK app, the GNOME Shell Quick Settings extension).
//
// Upstream IPC channels travel unchanged through one generic method:
//   Call(channel: s, argsJson: s) -> resultJson: s
// so a channel upstream adds tomorrow works without touching this file.

export const BUS_NAME = 'io.github.ds5bridge.Daemon';
export const OBJECT_PATH = '/io/github/ds5bridge/Daemon';
export const INTERFACE = 'io.github.ds5bridge.Daemon1';
export const ERROR_NAME = 'io.github.ds5bridge.Error';

/** Daemon-only channels, used by clients for the UI half of custom upstream handlers. */
export const DAEMON_CHANNELS = {
  /** (path: string) -> PicoFirmwareActionResult. The client picks the file. */
  flashPicoFirmwareFile: 'daemon:flashPicoFirmwareFile',
  /** () -> PicoFirmwareActionResult. The client asks for confirmation first. */
  nukePicoFlashConfirmed: 'daemon:nukePicoFlashConfirmed',
  /** () -> boolean. Whether a firmware action is running (window must not close the session). */
  firmwareActionRunning: 'daemon:firmwareActionRunning'
} as const;

const UNDEFINED_MARK = '__ds5_undefined__';

// Electron IPC uses structured clone, which keeps `undefined` (e.g. an omitted
// optional profile name). Plain JSON would turn it into null, so mark it.
export function encode(value: unknown): string {
  if (value === undefined) return JSON.stringify(UNDEFINED_MARK);
  return JSON.stringify(value, (_key, v) => (v === undefined ? UNDEFINED_MARK : v));
}

export function decode<T = unknown>(json: string): T {
  if (json === '') return undefined as T;
  const parsed = JSON.parse(json, (_key, v) => (v === UNDEFINED_MARK ? undefined : v));
  return (parsed === UNDEFINED_MARK ? undefined : parsed) as T;
}
