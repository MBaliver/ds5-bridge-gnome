// Fake ds5-bridged for UI development (Shell extension, GTK app) without a
// bridge, or inside a nested `dbus-run-session gnome-shell --devkit`.
//   node scripts/mock-daemon.mjs [snapshot.json]
// Setters update settings.<field> by naming convention (bridge:setFooBar -> fooBar
// / fooBarEnabled / fooBarPercent) and emit Snapshot, like the real daemon.
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const dbus = require('dbus-next');

const file = process.argv[2] ?? new URL('../dev/snapshot.sample.json', import.meta.url);
const snapshot = JSON.parse(fs.readFileSync(file, 'utf8'));
const { Interface, ACCESS_READ } = dbus.interface;
const lower = (s) => s[0].toLowerCase() + s.slice(1);

class Mock extends Interface {
  get State() { return snapshot.state; }
  get Connected() { return Boolean(snapshot.status?.controllerConnected); }
  get ControllerName() { return this.Connected ? (snapshot.status.controllerType === 'dualsense-edge' ? 'DualSense Edge' : 'DualSense') : ''; }
  get BatteryPercent() { return this.Connected ? (snapshot.status.batteryPercent ?? -1) : -1; }
  get Charging() { return false; }
  get UpstreamVersion() { return 'mock'; }
  Call(channel, argsJson) {
    const args = JSON.parse(argsJson);
    console.log('call', channel, argsJson);
    const name = channel.split(':')[1];
    if (name === 'getStatus') return JSON.stringify(snapshot);
    // Calibration and input, enough to drive the UI flows.
    if (name === 'sendStickCalibration') { this.cal = { op: args[0], target: args[1] }; return 'null'; }
    if (name === 'readCalibrationStatus') {
      const c = this.cal ?? { op: 1, target: 1 };
      return JSON.stringify({ received: true, bytes: [], target: c.target, code: c.op === 2 ? 2 : 1 });
    }
    if (name === 'setNvsUnlocked' || name === 'holdInputForwarding' || name === 'selectTesterController') return 'null';
    // AudioHapticsOutputDevice[] / AudioHapticsSession[] (shared/types.ts)
    if (name === 'listAudioHapticsOutputDevices') return JSON.stringify([
      { name: 'alsa_output.usb-GoXLR.Game', description: 'GoXLR Game', isDefault: false },
      { name: 'ds5-haptics-mix', description: 'DS5 Haptics Mix', isDefault: false }]);
    if (name === 'listAudioHapticsSessions') return JSON.stringify([
      { processId: 4242, displayName: 'Elden Ring', executableName: 'eldenring.exe', processPath: null, iconPath: null,
        sessionIdentifier: null, sessionInstanceIdentifier: null, state: 'active', endpointName: 'default', isSelected: false }]);
    // GNOME-daemon channels (daemon/main.ts getHapticsMix)
    if (channel === 'daemon:getHapticsMix' || channel === 'daemon:setHapticsMix') {
      if (channel === 'daemon:setHapticsMix') {
        this.mix = { enabled: args[0], excluded: args[1] ?? this.mix?.excluded ?? [{ key: 'discord', name: 'Discord' }, { key: 'spotify', name: 'Spotify' }, { key: 'firefox', name: 'Firefox' }] };
        snapshot.settings.audioReactiveHapticsSource = args[0] ? { kind: 'output-device', deviceName: 'ds5-haptics-mix', displayName: 'DS5 Haptics Mix' } : 'system-audio';
        snapshot.settings.audioReactiveHapticsEnabled = true;
        this.Snapshot(JSON.stringify(snapshot));
      }
      const mix = this.mix ?? { enabled: false, excluded: [{ key: 'discord', name: 'Discord' }, { key: 'spotify', name: 'Spotify' }, { key: 'firefox', name: 'Firefox' }] };
      return JSON.stringify({ ...mix, running: mix.enabled, sinkName: 'ds5-haptics-mix', streams: [
        { key: 'eldenring.exe', name: 'Elden Ring', included: true }, { key: 'spotify', name: 'Spotify', included: false },
        { key: 'discord', name: 'Discord', included: false }] });
    }
    if (name === 'setRawTriggerEffect') return JSON.stringify(snapshot);
    if (name === 'readControllerInput') {
      // Both sticks circle the rim: clockwise for one lap, then counterclockwise. 3 s per lap.
      this.t0 ??= Date.now();
      const t = (Date.now() - this.t0) / 3000;
      const a = (t < 1.1 ? t : 2.2 - t) * 2 * Math.PI;
      const x = Math.round(128 + 127 * Math.cos(a)), y = Math.round(128 + 127 * Math.sin(a));
      // Same shape as BridgeService.readControllerInput (ControllerInputSnapshot).
      const pressed = Math.floor(t * 4) % 6;
      const state = {
        leftStickX: x, leftStickY: y, rightStickX: 256 - x, rightStickY: y,
        leftTrigger: Math.round(127 + 127 * Math.sin(a)), rightTrigger: Math.round(127 - 127 * Math.sin(a)),
        dpadUp: pressed === 0, dpadDown: false, dpadLeft: false, dpadRight: pressed === 1,
        square: pressed === 2, cross: pressed === 3, circle: false, triangle: pressed === 4, l1: pressed === 5, r1: false,
        l2Pressed: false, r2Pressed: true, create: false, options: false, l3: false, r3: false, home: false,
        touchpadButton: false, mute: false, edgeLeftFunction: false, edgeRightFunction: false,
        edgeLeftPaddle: false, edgeRightPaddle: false,
        gyroX: 12, gyroY: -3, gyroZ: 7, accelX: 120, accelY: 8150, accelZ: -300, sensorTimestamp: Date.now(),
        touchPoints: [{ active: true, contactId: 1, x: 960 + 600 * Math.cos(a), y: 540 + 300 * Math.sin(a) },
                      { active: false, contactId: 2, x: 0, y: 0 }],
        batteryPercent: 82, rawPowerState: 0, charging: false, headsetPlugged: false,
        microphonePlugged: false, microphoneMuted: false
      };
      return JSON.stringify({ controllerConnected: true, raw: [1, x, y, 256 - x, y, 0, 0, 8], state });
    }
    if (name === 'getVersion') return '"mock"';
    if (name === 'selectControllerProfile') snapshot.settings.selectedControllerProfileId = args[0];
    else if (name === 'sleepController') {
      snapshot.status.controllerConnected = false;
      Interface.emitPropertiesChanged(this, { Connected: false, ControllerName: '', BatteryPercent: -1 }, []);
    } else if (name === 'setMicMute') snapshot.settings.micMuted = args[0];
    else if (name === 'setChordConfiguration') [snapshot.settings.chordFunctions, snapshot.settings.chordAssignments] = args;
    else if (name === 'setButtonRemap') snapshot.settings.buttonRemappingDraft[args[0]] = args[1];
    else if (name.startsWith('set')) {
      const base = lower(name.slice(3));
      const key = [base, `${base}Percent`, base.replace(/Enabled$/, '') + 'Enabled']
        .find((k) => k in snapshot.settings);
      if (key) snapshot.settings[key] = args[0];
    }
    this.Snapshot(JSON.stringify(snapshot));
    return JSON.stringify(snapshot);
  }
  Snapshot(json) { return json; }
  Toast(t, b) { return [t, b]; }
}
Mock.configureMembers({
  properties: Object.fromEntries([['State', 's'], ['Connected', 'b'], ['ControllerName', 's'], ['BatteryPercent', 'i'], ['Charging', 'b'], ['UpstreamVersion', 's']]
    .map(([n, s]) => [n, { signature: s, access: ACCESS_READ }])),
  methods: { Call: { inSignature: 'ss', outSignature: 's' } },
  signals: { Snapshot: { signature: 's' }, Toast: { signature: 'ss' } }
});

const bus = dbus.sessionBus();
await bus.requestName('io.github.ds5bridge.Daemon', dbus.NameFlag.DO_NOT_QUEUE);
bus.export('/io/github/ds5bridge/Daemon', new Mock('io.github.ds5bridge.Daemon1'));
console.log('mock ds5-bridged up');
