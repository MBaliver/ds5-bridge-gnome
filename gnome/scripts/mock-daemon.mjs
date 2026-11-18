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
