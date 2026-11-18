// DS5 Bridge Quick Settings tile + top-bar indicator.
// A thin client of ds5-bridged (io.github.ds5bridge.Daemon on the session bus):
// properties drive the tile and indicator, the Snapshot signal drives the menu,
// and every action is an upstream IPC channel sent through Call().

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.ds5bridge.Daemon';
const OBJECT_PATH = '/io/github/ds5bridge/Daemon';
const IFACE_XML = `
<node>
  <interface name="io.github.ds5bridge.Daemon1">
    <method name="Call">
      <arg type="s" direction="in" name="channel"/>
      <arg type="s" direction="in" name="argsJson"/>
      <arg type="s" direction="out" name="resultJson"/>
    </method>
    <signal name="Snapshot"><arg type="s" name="json"/></signal>
    <signal name="Toast"><arg type="s" name="title"/><arg type="s" name="body"/></signal>
    <property name="State" type="s" access="read"/>
    <property name="Connected" type="b" access="read"/>
    <property name="ControllerName" type="s" access="read"/>
    <property name="BatteryPercent" type="i" access="read"/>
    <property name="Charging" type="b" access="read"/>
  </interface>
</node>`;
const IFACE_INFO = Gio.DBusNodeInfo.new_for_xml(IFACE_XML).interfaces[0];

const ICON = 'input-gaming-symbolic';
const APP_ID = 'ds5-bridge.desktop';
const PERSONAS = [
    ['dualsense', 'DualSense'],
    ['dualsense-edge', 'DualSense Edge'],
    ['ds4', 'DualShock 4'],
    ['xbox', 'Xbox'],
];
const UNDEFINED_MARK = '__ds5_undefined__';

function decode(json) {
    if (!json)
        return undefined;
    const value = JSON.parse(json);
    return value === UNDEFINED_MARK ? undefined : value;
}

const BridgeToggle = GObject.registerClass(
class BridgeToggle extends QuickSettings.QuickMenuToggle {
    _init(proxy) {
        super._init({title: 'DualSense', iconName: ICON, toggleMode: false});
        this._proxy = proxy;
        this._snapshot = null;

        // Like Power Mode: the tile itself opens the menu; "checked" = controller connected.
        this.connect('clicked', () => this.menu.open());

        this._profileSection = new PopupMenu.PopupMenuSection();
        this.menu.addMenuItem(this._profileSection);

        this._controlsSeparator = new PopupMenu.PopupSeparatorMenuItem();
        this.menu.addMenuItem(this._controlsSeparator);

        this._persona = new PopupMenu.PopupSubMenuMenuItem('', false);
        this._personaItems = new Map();
        for (const [id, label] of PERSONAS) {
            const item = this._persona.menu.addAction(label, () => this._call('bridge:setHostPersonaMode', id));
            this._personaItems.set(id, item);
        }
        this.menu.addMenuItem(this._persona);

        this._haptics = this._switch('Haptics', on => this._call('bridge:setHapticsEnabled', on));
        this._mic = this._switch('Microphone', on => this._call('bridge:setMicMute', !on));
        this._lightbar = this._switch('Light Bar', on => this._call('bridge:setLightbarEnabled', on));

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._sleep = this.menu.addAction('Turn Off Controller', () => this._call('bridge:sleepController'));
        this.menu.addAction('DS5 Bridge Settings', () => {
            Main.panel.closeQuickSettings();
            Shell.AppSystem.get_default().lookup_app(APP_ID)?.activate();
        });

        this._sync();
    }

    _switch(label, onToggle) {
        const item = new PopupMenu.PopupSwitchMenuItem(label, false);
        // setToggleState() during _sync() also emits 'toggled'; only forward user changes.
        item.connect('toggled', (_item, state) => {
            if (!this._syncing)
                onToggle(state);
        });
        this.menu.addMenuItem(item);
        return item;
    }

    _call(channel, ...args) {
        this._proxy.call(
            'Call',
            new GLib.Variant('(ss)', [channel, JSON.stringify(args)]),
            Gio.DBusCallFlags.NONE, -1, null,
            (proxy, result) => {
                try {
                    proxy.call_finish(result);
                } catch (e) {
                    console.warn(`[ds5-bridge] ${channel} failed: ${e.message}`);
                }
            });
    }

    refreshSnapshot() {
        if (!this._proxy.g_name_owner) {
            this._snapshot = null;
            this._sync();
            return;
        }
        this._proxy.call('Call', new GLib.Variant('(ss)', ['bridge:getStatus', '[]']),
            Gio.DBusCallFlags.NONE, -1, null, (proxy, result) => {
                try {
                    const [json] = proxy.call_finish(result).deepUnpack();
                    this.setSnapshot(decode(json));
                } catch (e) {
                    console.warn(`[ds5-bridge] getStatus failed: ${e.message}`);
                }
            });
    }

    setSnapshot(snapshot) {
        this._snapshot = snapshot;
        this._sync();
    }

    _prop(name) {
        return this._proxy.get_cached_property(name)?.unpack();
    }

    _subtitle(running, state, connected) {
        if (!running)
            return 'Service Not Running';
        if (state === 'no-bridge')
            return 'Bridge Not Found';
        if (!connected)
            return 'Disconnected';
        const battery = this._prop('BatteryPercent');
        if (battery === undefined || battery < 0)
            return 'Connected';
        return this._prop('Charging') ? `${battery}% · Charging` : `${battery}%`;
    }

    _sync() {
        const running = Boolean(this._proxy.g_name_owner);
        const state = this._prop('State');
        const connected = running && Boolean(this._prop('Connected'));
        const name = (connected && this._prop('ControllerName')) || 'DualSense';
        const subtitle = this._subtitle(running, state, connected);

        this.set({title: name, subtitle, checked: connected});
        this.menu.setHeader(ICON, name, subtitle);

        const settings = running && state !== 'no-bridge' ? this._snapshot?.settings : null;
        for (const item of [this._controlsSeparator, this._persona, this._haptics, this._mic, this._lightbar])
            item.visible = Boolean(settings);
        this._sleep.visible = connected;

        this._profileSection.removeAll();
        if (!settings)
            return;

        for (const profile of settings.controllerProfiles ?? []) {
            const item = this._profileSection.addAction(profile.name,
                () => this._call('bridge:selectControllerProfile', profile.id));
            item.setOrnament(profile.id === settings.selectedControllerProfileId
                ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);
        }

        const persona = settings.hostPersonaMode;
        this._persona.label.text = `Emulate: ${PERSONAS.find(([id]) => id === persona)?.[1] ?? persona}`;
        for (const [id, item] of this._personaItems)
            item.setOrnament(id === persona ? PopupMenu.Ornament.CHECK : PopupMenu.Ornament.NONE);

        this._syncing = true;
        try {
            this._haptics.setToggleState(Boolean(settings.hapticsEnabled));
            this._mic.setToggleState(!settings.micMuted);
            this._lightbar.setToggleState(Boolean(settings.lightbarEnabled));
        } finally {
            this._syncing = false;
        }
    }

    sync() {
        this._sync();
    }
});

const BridgeIndicator = GObject.registerClass(
class BridgeIndicator extends QuickSettings.SystemIndicator {
    _init(proxy) {
        super._init();
        this._proxy = proxy;
        this._icon = this._addIndicator();
        this._icon.icon_name = ICON;
        this.toggle = new BridgeToggle(proxy);
        this.quickSettingsItems.push(this.toggle);
        this.sync();
    }

    sync() {
        // Only in the top bar while a controller is connected, like Bluetooth.
        this._icon.visible = Boolean(this._proxy.g_name_owner)
            && Boolean(this._proxy.get_cached_property('Connected')?.unpack());
        this.toggle.sync();
    }

    destroy() {
        this.quickSettingsItems.forEach(item => item.destroy());
        super.destroy();
    }
});

export default class Ds5BridgeExtension extends Extension {
    enable() {
        this._proxy = new Gio.DBusProxy({
            g_connection: Gio.DBus.session,
            g_name: BUS_NAME,
            g_object_path: OBJECT_PATH,
            g_interface_name: IFACE_INFO.name,
            g_interface_info: IFACE_INFO,
            // Never auto-start the daemon from the shell; systemd owns its lifecycle.
            g_flags: Gio.DBusProxyFlags.DO_NOT_AUTO_START,
        });
        this._proxy.init(null);

        this._indicator = new BridgeIndicator(this._proxy);
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);

        this._proxy.connectObject(
            'g-properties-changed', () => this._indicator.sync(),
            'notify::g-name-owner', () => {
                this._indicator.sync();
                this._indicator.toggle.refreshSnapshot();
            },
            'g-signal', (_proxy, _sender, signal, params) => {
                if (signal === 'Snapshot')
                    this._indicator.toggle.setSnapshot(decode(params.deepUnpack()[0]));
            },
            this);
        this._indicator.toggle.refreshSnapshot();

        const selftest = GLib.getenv('DS5_BRIDGE_SELFTEST');
        if (selftest)
            this._selftest(selftest);
    }

    disable() {
        this._proxy?.disconnectObject(this);
        this._proxy = null;
        for (const id of this._timeouts ?? [])
            GLib.Source.remove(id);
        this._timeouts = null;
        this._indicator?.destroy();
        this._indicator = null;
    }

    // Dev only: DS5_BRIDGE_SELFTEST=/path/prefix gnome-shell --devkit (with a mock daemon).
    _selftest(prefix) {
        this._timeouts = [];
        const shot = name => {
            const file = Gio.File.new_for_path(`${prefix}-${name}.png`);
            const stream = file.replace(null, false, Gio.FileCreateFlags.NONE, null);
            new Shell.Screenshot().screenshot(false, stream, () => stream.close(null));
        };
        const quickSettings = Main.panel.statusArea.quickSettings;
        const steps = [
            [4000, () => quickSettings.menu.open()],
            [1500, () => shot('1-tile')],
            [500, () => this._indicator.toggle.menu.open()],
            [1500, () => shot('2-menu')],
            [500, () => this._indicator.toggle._persona.setSubmenuShown(true)],
            [1500, () => shot('3-submenu')],
        ];
        let at = 0;
        for (const [delay, fn] of steps) {
            at += delay;
            this._timeouts.push(GLib.timeout_add(GLib.PRIORITY_DEFAULT, at, () => {
                fn();
                return GLib.SOURCE_REMOVE;
            }));
        }
    }
}
