#!/usr/bin/env python3
"""DS5 Bridge for GNOME: a GTK4/libadwaita front end for ds5-bridged.

Every action is an upstream IPC channel sent through the daemon's generic
Call(channel, argsJson) method, and every widget is refreshed from the
upstream BridgeSnapshot, so this file only decides presentation.
Screens it does not cover yet open the classic (upstream) interface.
"""
import json
import os
import sys
import time

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

APP_ID = 'io.github.ds5bridge.App'
BUS_NAME = 'io.github.ds5bridge.Daemon'
OBJECT_PATH = '/io/github/ds5bridge/Daemon'
IFACE = 'io.github.ds5bridge.Daemon1'
UNDEFINED_MARK = '__ds5_undefined__'
HERE = os.path.dirname(os.path.realpath(__file__))
CLASSIC_UI = os.path.join(HERE, '..', 'bin', 'ds5-bridge-ui')

PERSONAS = [('dualsense', 'DualSense'), ('dualsense-edge', 'DualSense Edge'),
            ('ds4', 'DualShock 4'), ('xbox', 'Xbox')]
POLLING = [('250', '250 Hz'), ('500', '500 Hz'), ('1000', '1000 Hz')]
MUTE_MODES = [('normal', 'Mute Microphone'), ('quiet', 'Quiet Mode Toggle'),
              ('keyboard', 'Keyboard Key'), ('chord', 'Chord Starter')]
TRIGGER_TESTS = [('feedback', 'Feedback'), ('weapon', 'Weapon'), ('vibration', 'Vibration')]
REACTIVE_SOURCES = [('system-audio', 'System Audio'), ('controller-audio', 'Controller Audio')]
BASS_FOCUS = [('deep', 'Deep'), ('balanced', 'Balanced'), ('punchy', 'Punchy'), ('wide', 'Wide')]
RESPONSE = [('subtle', 'Subtle'), ('balanced', 'Balanced'), ('strong', 'Strong')]
ATTACK = [('soft', 'Soft'), ('balanced', 'Balanced'), ('fast', 'Fast'), ('sharp', 'Sharp')]
RELEASE = [('tight', 'Tight'), ('balanced', 'Balanced'), ('smooth', 'Smooth'), ('long', 'Long')]
# Same limits as the upstream UI (App.tsx).
STANDARD_FEEDBACK_MAX = 200
BOOSTED_FEEDBACK_MAX = 500
POWER_SAVING_CAP = 60

# Artwork shipped with upstream (repo-root assets/).
ASSETS = os.path.join(HERE, '..', '..', 'assets')
CONTROLLER_ART = os.path.join(ASSETS, 'controllers', 'dualsense-edge-front.svg')
GLYPH_DIR = os.path.join(ASSETS, 'glyphs', 'ps5-buttons-outline-white', 'svg')

# Button remapping, mirroring upstream App.tsx (REMAP_BUTTONS & co).
REMAP_LABELS = {
    'l2': 'L2', 'l1': 'L1', 'create': 'Create', 'dpad-up': 'D-pad Up', 'dpad-left': 'D-pad Left',
    'dpad-down': 'D-pad Down', 'dpad-right': 'D-pad Right', 'l3': 'L3', 'r2': 'R2', 'r1': 'R1',
    'options': 'Options', 'triangle': 'Triangle', 'circle': 'Circle', 'cross': 'Cross', 'square': 'Square',
    'r3': 'R3', 'lb': 'Left Back Button', 'rb': 'Right Back Button', 'lfn': 'Left Function Button',
    'rfn': 'Right Function Button', 'ps': 'PS Button',
}
REMAP_GLYPHS = {
    'l2': 'L2', 'l1': 'L1', 'create': 'Create', 'dpad-up': 'D-Pad Up', 'dpad-left': 'D-Pad Left',
    'dpad-down': 'D-Pad Down', 'dpad-right': 'D-Pad Right', 'l3': 'Left Stick Click', 'r2': 'R2', 'r1': 'R1',
    'options': 'Options', 'triangle': 'Triangle', 'circle': 'Circle', 'cross': 'Cross', 'square': 'Square',
    'r3': 'Right Stick Click', 'ps': 'Home',
}
REMAP_TEXT_GLYPHS = {'lb': 'LB', 'rb': 'RB', 'lfn': 'LFN', 'rfn': 'RFN'}
REMAP_LEFT = ['l2', 'l1', 'create', 'dpad-up', 'dpad-right', 'dpad-down', 'dpad-left', 'l3']
REMAP_RIGHT = ['r2', 'r1', 'options', 'triangle', 'circle', 'cross', 'r3', 'square']
REMAP_EDGE = ['lb', 'rb', 'lfn', 'rfn']
REMAP_STANDARD_TARGETS = ['triangle', 'circle', 'cross', 'square', 'dpad-up', 'dpad-right', 'dpad-down',
                          'dpad-left', 'l1', 'r1', 'l2', 'r2', 'l3', 'r3', 'create', 'options']
REMAP_TARGETS = REMAP_STANDARD_TARGETS + ['ps']

# Mute button as a keyboard key (USB HID usages, upstream MUTE_KEY_OPTIONS).
MUTE_KEYS = ([(f'F{i + 1}', 0x3A + i) for i in range(12)] + [(f'F{i + 13}', 0x68 + i) for i in range(12)]
             + [(chr(65 + i), 0x04 + i) for i in range(26)]
             + [(str((i + 1) % 10), 0x1E + i) for i in range(10)]
             + [('Enter', 0x28), ('Escape', 0x29), ('Backspace', 0x2A), ('Tab', 0x2B), ('Space', 0x2C),
                ('-', 0x2D), ('=', 0x2E), ('[', 0x2F), (']', 0x30), ('\\', 0x31), (';', 0x33), ("'", 0x34),
                ('`', 0x35), (',', 0x36), ('.', 0x37), ('/', 0x38), ('Print Screen', 0x46), ('Scroll Lock', 0x47),
                ('Pause', 0x48), ('Insert', 0x49), ('Home', 0x4A), ('Page Up', 0x4B), ('Delete', 0x4C),
                ('End', 0x4D), ('Page Down', 0x4E), ('Right Arrow', 0x4F), ('Left Arrow', 0x50),
                ('Down Arrow', 0x51), ('Up Arrow', 0x52)])
MUTE_MODIFIERS = [('Ctrl', 0x01), ('Shift', 0x02), ('Alt', 0x04), ('Super', 0x08)]
MUTE_BEHAVIORS = [('tap', 'Tap Once'), ('hold', 'Hold While Pressed')]

# Chords (upstream protocol.ts / App.tsx).
MAX_CHORD_ASSIGNMENTS = 16
MAX_CHORD_FUNCTION_NAME = 16
MAX_KEYBOARD_FUNCTION_KEYS = 4
CHORD_STARTERS = [('ps', 'PS Button'), ('lfn', 'Left Function'), ('rfn', 'Right Function'), ('mute', 'Mute Button')]
CHORD_EDGE_RESERVED = {'triangle', 'circle', 'cross', 'square'}
CHORD_FUNCTION_TYPES = [('keyboard', 'Keyboard Shortcut'), ('media', 'Media Action'),
                        ('controller-setting', 'Controller Setting')]
CHORD_MEDIA = [('play-pause', 'Play / Pause'), ('next-track', 'Next Track'), ('previous-track', 'Previous Track'),
               ('mute', 'Mute Output'), ('volume-up', 'Volume Up'), ('volume-down', 'Volume Down')]
CHORD_SETTINGS = [
    ('toggle-audio-haptics', 'Toggle Audio-Reactive Haptics'), ('toggle-lightbar-override', 'Toggle Light Bar Override'),
    ('toggle-mic-mute', 'Toggle Microphone'), ('sleep-controller', 'Turn Off Controller'),
    ('show-battery', 'Show Battery Level'), ('persona-dualsense', 'Emulate DualSense'),
    ('persona-ds4', 'Emulate DualShock 4'), ('persona-xbox', 'Emulate Xbox'),
    ('speaker-up', 'Speaker Volume Up'), ('speaker-down', 'Speaker Volume Down'),
    ('mic-up', 'Microphone Volume Up'), ('mic-down', 'Microphone Volume Down'),
    ('haptics-up', 'Haptics Stronger'), ('haptics-down', 'Haptics Weaker'),
    ('rumble-up', 'Rumble Stronger'), ('rumble-down', 'Rumble Weaker'),
    ('triggers-up', 'Trigger Intensity Up'), ('triggers-down', 'Trigger Intensity Down'),
    ('lighting-up', 'Light Bar Brighter'), ('lighting-down', 'Light Bar Dimmer'),
]
CHORD_KEYS = ([(k, k) for k in ('Esc', 'Enter', 'Space', 'Tab', 'Backspace', 'Delete', 'Insert', 'Home', 'End',
                                 'Page Up', 'Page Down')]
              + [('Up Arrow', 'Up'), ('Down Arrow', 'Down'), ('Left Arrow', 'Left'), ('Right Arrow', 'Right')]
              + [(k, k) for k in ('Print Screen', 'Pause', 'Caps Lock', 'Num Lock', 'Scroll Lock', 'Menu')]
              + [(f'F{i}', f'F{i}') for i in range(1, 25)]
              + [(c, c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890']
              + [(f'Numpad {d}', f'Numpad{d}') for d in '0123456789'])
CHORD_MODIFIERS = [('Ctrl', 'Ctrl'), ('Shift', 'Shift'), ('Alt', 'Alt'), ('Super', 'Win')]


MIX_SINK_NAME = 'ds5-haptics-mix'


def audio_source_key(source):
    if isinstance(source, dict) and source.get('kind') == 'output-device' and source.get('deviceName') == MIX_SINK_NAME:
        return 'mix'
    if isinstance(source, dict) and source.get('kind') == 'output-device':
        return f'output-device:{source.get("deviceName")}'
    if isinstance(source, dict) and source.get('kind') == 'app-session':
        if source.get('processPath'):
            return f'app-path:{source["processPath"].lower()}'
        if source.get('executableName'):
            return f'app-exe:{source["executableName"].lower()}'
        return f'app-pid:{max(0, round(source.get("processId", 0)))}'
    return source if source in ('controller-audio', 'system-audio') else 'system-audio'


def audio_source_label(source):
    if source == 'mix' or audio_source_key(source) == 'mix':
        return 'All Apps Except…'
    if isinstance(source, dict) and source.get('kind') == 'output-device':
        return f'Output · {source.get("displayName") or source.get("deviceName")}'
    if isinstance(source, dict) and source.get('kind') == 'app-session':
        name = source.get('displayName') or (source.get('executableName') or '').rsplit('.', 1)[0] or 'Selected App'
        return f'App · {name}'
    return dict(REACTIVE_SOURCES).get(source, 'System Audio')


def audio_source_from_session(session):
    out = {'kind': 'app-session', 'processId': session['processId'], 'displayName': session['displayName']}
    for key in ('executableName', 'processPath', 'sessionIdentifier', 'sessionInstanceIdentifier'):
        if session.get(key):
            out[key] = session[key]
    return out


def step_action(action):
    return action.endswith('-up') or action.endswith('-down')


def default_step(action):
    return 20 if action.split('-')[0] in ('haptics', 'rumble') else 10


def label_of(options, value, fallback=None):
    return next((label for key, label in options if key == value), fallback if fallback is not None else str(value))


def chord_function_summary(func):
    kind = func.get('type')
    if kind == 'keyboard':
        return ' + '.join('Super' if k == 'Win' else k for k in func.get('keys', []))
    if kind == 'media':
        return label_of(CHORD_MEDIA, func.get('action'))
    text = label_of(CHORD_SETTINGS, func.get('action'))
    return f'{text} ({func.get("stepPercent")}%)' if step_action(func.get('action', '')) else text


def new_id(prefix):
    return f'{prefix}-{int(time.time() * 1000):x}-{os.urandom(3).hex()}'


class Glyphs:
    """Upstream's white outline PS5 button glyphs, recolored to the theme's text color."""

    def __init__(self):
        self.cache = {}

    def texture(self, name, size, rgba, crop=False):
        color = '#{:02x}{:02x}{:02x}'.format(*(round(c * 255) for c in (rgba.red, rgba.green, rgba.blue)))
        key = (name, size, color, crop)
        if key not in self.cache:
            path = os.path.join(GLYPH_DIR, f'{name}.svg')
            try:
                with open(path, encoding='utf-8') as fh:
                    svg = fh.read()
            except OSError:
                return None
            svg = svg.replace('#fff', color).replace('#FFF', color)
            if crop:
                # The glyphs carry ~15% padding; trim it so they match 16 px symbolic icons.
                svg = svg.replace('viewBox="0 0 512 512"', 'viewBox="72 72 368 368"', 1)
            gi.require_version('GdkPixbuf', '2.0')
            from gi.repository import GdkPixbuf
            loader = GdkPixbuf.PixbufLoader()
            loader.set_size(size * 2, size * 2)  # 2x for HiDPI; GtkPicture scales down
            loader.write(svg.encode())
            loader.close()
            ok, png = loader.get_pixbuf().save_to_bufferv('png', [], [])
            self.cache[key] = Gdk.Texture.new_from_bytes(GLib.Bytes.new(png))
        return self.cache[key]


# ---------------------------------------------------------- trigger effects
# Port of upstream shared/trigger-effects.ts (encoding shown as "bytes on the wire").

TRIGGER_EFFECT_TYPES = [
    ('off', 'Off'), ('resistance', 'Resistance'), ('weapon', 'Weapon'), ('auto', 'Vibration'),
    ('zoned-feedback', 'Zoned Resistance'), ('zoned-weapon', 'Zoned Weapon'), ('zoned-vibration', 'Zoned Vibration'),
]
TRIGGER_ZONES = 10
TRIGGER_ZONE_FORCE_MAX = 7
TRIGGER_FREQUENCY_MAX = 15
TRIGGER_ZONE_FREQUENCY_MAX = 255
# Upstream's built-in "Default": legacy weapon 20/60/85 as migrated by trigger-effect-migration.ts.
TRIGGER_DEFAULT_EFFECT = {'type': 'zoned-weapon', 'start': 2, 'end': 6, 'force': 6}


def default_trigger_effect(kind):
    return {
        'off': {'type': 'off'},
        'resistance': {'type': 'resistance', 'start': 40, 'force': 180},
        'weapon': {'type': 'weapon', 'start': 15, 'end': 100, 'force': 255},
        'auto': {'type': 'auto', 'start': 20, 'force': 200, 'frequency': 10},
        'zoned-feedback': {'type': 'zoned-feedback', 'zones': [None, None, 3, 4, 5, 5, 5, 5, 5, 5]},
        'zoned-weapon': {'type': 'zoned-weapon', 'start': 3, 'end': 7, 'force': 6},
        'zoned-vibration': {'type': 'zoned-vibration', 'zones': [None, None, 4, 4, 4, 4, 4, 4, 4, 4], 'frequency': 8},
    }[kind]


def _clamp(value, lo, hi):
    import math
    return max(lo, min(hi, math.floor(value + 0.5)))  # JS Math.round semantics, like upstream


def encode_trigger_effect(effect):
    out = [0] * 11

    def pack(zones, offset):
        mask, bits = 0, 0
        for zone in range(TRIGGER_ZONES):
            level = zones[zone] if zone < len(zones) else None
            if level is None:
                continue
            mask |= 1 << zone
            bits |= _clamp(level, 0, TRIGGER_ZONE_FORCE_MAX) << (3 * zone)
        out[offset], out[offset + 1] = mask & 0xff, (mask >> 8) & 0xff
        for i in range(4):
            out[offset + 2 + i] = (bits >> (8 * i)) & 0xff

    kind = effect['type']
    if kind == 'off':
        out[0] = 0x05
    elif kind == 'resistance':
        out[:3] = [0x01, _clamp(effect['start'], 0, 255), _clamp(effect['force'], 0, 255)]
    elif kind == 'weapon':
        start = _clamp(effect['start'], 0, 255)
        out[:4] = [0x02, start, min(max(_clamp(effect['end'], 0, 255), start + 1), 255), _clamp(effect['force'], 0, 255)]
    elif kind == 'auto':
        out[:4] = [0x06, _clamp(effect['start'], 0, 255), _clamp(effect['force'], 0, 255),
                   _clamp(effect['frequency'], 0, TRIGGER_FREQUENCY_MAX)]
    elif kind == 'zoned-feedback':
        out[0] = 0x21
        pack(effect['zones'], 1)
    elif kind == 'zoned-weapon':
        start = _clamp(effect['start'], 0, TRIGGER_ZONES - 1)
        end = max(_clamp(effect['end'], 0, TRIGGER_ZONES - 1), start + 1)
        mask = (1 << start) | (1 << min(end, TRIGGER_ZONES - 1))
        out[:4] = [0x25, mask & 0xff, (mask >> 8) & 0xff, _clamp(effect['force'], 0, TRIGGER_ZONE_FORCE_MAX)]
    elif kind == 'zoned-vibration':
        out[0] = 0x26
        pack(effect['zones'], 1)
        out[9] = _clamp(effect['frequency'], 0, TRIGGER_ZONE_FREQUENCY_MAX)
    return out


# Stick calibration (upstream protocol.ts CALIBRATION_* and StickSweep.tsx).
CAL_OP_BEGIN, CAL_OP_STORE, CAL_OP_SAMPLE = 1, 2, 3
CAL_CENTRE, CAL_RANGE = 1, 2
CAL_OPEN, CAL_COMMITTED, CAL_ALREADY_CLOSED = 1, 2, 3
CAL_CONFIRM_PHRASE = 'MAKE PERMANENT'
SWEEP_SECTORS = 48
SWEEP_RIM = 0.85
SWEEP_MIN_SECTOR_MS = 30
SWEEP_PACE_WINDOW = 8
INPUT_HOLD_MS = 2000
INPUT_HOLD_RENEW_MS = 700


def calibration_step_accepted(status, target, expected):
    if not status or not status.get('received') or status.get('target') != target:
        return False
    return status.get('code') == expected or (expected == CAL_COMMITTED and status.get('code') == CAL_ALREADY_CLOSED)


class Sweep:
    """Directional rim coverage for the range calibration (port of StickSweep.tsx recordSweep)."""

    def __init__(self):
        self.sectors = [0.0] * SWEEP_SECTORS
        self.cw = [False] * SWEEP_SECTORS
        self.ccw = [False] * SWEEP_SECTORS
        self.last = None
        self.direction = 0
        self.entries = []
        self.x = self.y = 0.0

    def record(self, xb, yb, now_ms):
        import math
        x, y = (xb - 128) / 127, (yb - 128) / 127
        self.x, self.y = x, y
        magnitude = min(1.0, math.hypot(x, y))
        if magnitude < 0.25:
            return
        sector = int(((math.atan2(y, x) + math.pi) / (2 * math.pi)) * SWEEP_SECTORS) % SWEEP_SECTORS
        self.sectors[sector] = max(self.sectors[sector], magnitude)
        if magnitude < SWEEP_RIM:
            return
        if self.last is None:
            self.last, self.direction, self.entries = sector, 0, [now_ms]
            return
        if sector == self.last:
            return
        delta = (sector - self.last + SWEEP_SECTORS) % SWEEP_SECTORS
        step = 1 if delta == 1 else -1 if delta == SWEEP_SECTORS - 1 else 0
        if step == 0 or (self.direction != 0 and step != self.direction):
            self.direction, self.entries = step, [now_ms]
        else:
            self.direction = step
            self.entries = (self.entries + [now_ms])[-SWEEP_PACE_WINDOW:]
            steps = len(self.entries) - 1
            if steps > 0 and now_ms - self.entries[0] >= steps * SWEEP_MIN_SECTOR_MS:
                (self.cw if step == 1 else self.ccw)[sector] = True
        self.last = sector

    def coverage(self, direction):
        values = self.cw if direction == 'cw' else self.ccw
        return sum(values) / SWEEP_SECTORS

    @property
    def complete(self):
        return all(self.cw) and all(self.ccw)


class LocalState:
    """Front-end-only state (upstream keeps the Trigger Lab in the renderer's localStorage)."""

    def __init__(self):
        self.path = os.path.join(GLib.get_user_config_dir(), 'DS5 Bridge', 'gnome-ui.json')
        try:
            with open(self.path, encoding='utf-8') as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(self.data, fh, indent=1)
        os.replace(tmp, self.path)


GLYPHS = Glyphs()


def glyph_picture(name, size=24, crop=False):
    """An upstream glyph by file name (e.g. 'R2', 'Left Stick'), recolored to the text color."""
    image = Gtk.Image(pixel_size=size, valign=Gtk.Align.CENTER)

    def paint(*_):
        texture = GLYPHS.texture(name, size, image.get_color(), crop)
        if texture:
            image.set_from_paintable(texture)
    image.connect('realize', paint)
    Adw.StyleManager.get_default().connect('notify::dark', paint)
    return image


def glyph_widget(button_id, size=24):
    """A glyph image for a remap button id (text pill for the Edge-only buttons)."""
    if button_id in REMAP_TEXT_GLYPHS:
        label = Gtk.Label(label=REMAP_TEXT_GLYPHS[button_id], width_request=size, valign=Gtk.Align.CENTER)
        label.add_css_class('caption-heading')
        label.add_css_class('ds5-pill')
        return label
    return glyph_picture(REMAP_GLYPHS.get(button_id, ''), size)


def controller_label(kind):
    return {'dualsense': 'DualSense', 'dualsense-edge': 'DualSense Edge'}.get(kind, 'Controller')


def decode(text):
    if text == '':
        return None

    def fix(value):
        if value == UNDEFINED_MARK:
            return None
        if isinstance(value, list):
            return [fix(v) for v in value]
        if isinstance(value, dict):
            return {k: fix(v) for k, v in value.items()}
        return value
    return fix(json.loads(text))


def dig(obj, path, default=None):
    for key in path.split('.'):
        if not isinstance(obj, dict) or key not in obj:
            return default
        obj = obj[key]
    return obj


# ----------------------------------------------------------------- D-Bus

class Daemon(GObject.Object):
    """Session-bus client of ds5-bridged."""
    __gsignals__ = {
        'snapshot': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'available': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        'error': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        # Not DO_NOT_AUTO_START: opening the app may D-Bus-activate the service.
        self.proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None,
            BUS_NAME, OBJECT_PATH, IFACE, None)
        self.proxy.connect('g-signal', self._on_signal)
        self.proxy.connect('notify::g-name-owner', lambda *_: self.refresh())

    @property
    def running(self):
        return self.proxy.get_name_owner() is not None

    def refresh(self):
        self.emit('available', self.running)
        self.call('bridge:getStatus', done=lambda snap: self.emit('snapshot', snap), quiet=True)

    def call(self, channel, *args, done=None, quiet=False, fail=None):
        def finish(proxy, result):
            try:
                (text,) = proxy.call_finish(result).unpack()
            except GLib.Error as error:
                message = Gio.DBusError.get_remote_error(error) and error.message.split(': ', 1)[-1] or error.message
                if fail:
                    fail(message)
                elif not quiet:
                    self.emit('error', message)
                return
            value = decode(text)
            # Most setters return the new snapshot; use it right away.
            if isinstance(value, dict) and 'settings' in value and 'state' in value:
                self.emit('snapshot', value)
            if done:
                done(value)
        self.proxy.call('Call', GLib.Variant('(ss)', (channel, json.dumps(list(args)))),
                        Gio.DBusCallFlags.NONE, 120000, None, finish)

    def _on_signal(self, _proxy, _sender, signal, params):
        if signal == 'Snapshot':
            self.emit('snapshot', decode(params.unpack()[0]))


# --------------------------------------------------------------- widgets

class Binder:
    """Two-way glue between rows and the snapshot.

    Snapshot -> widget updates are suppressed while the user is changing the
    widget (and shortly after), so a slider being dragged is not yanked back
    by a snapshot that predates the change.
    """
    HOLD_SECONDS = 1.5

    def __init__(self, window):
        self.window = window
        self.syncers = []
        self.syncing = False

    def sync(self, snapshot):
        self.syncing = True
        try:
            for fn in self.syncers:
                fn(snapshot)
        finally:
            self.syncing = False

    def _user_touch(self, widget):
        widget._ds5_touched = time.monotonic()

    def _held(self, widget):
        return time.monotonic() - getattr(widget, '_ds5_touched', 0) < self.HOLD_SECONDS

    def switch(self, title, get, on_set, subtitle=None):
        row = Adw.SwitchRow(title=title, subtitle=subtitle or '')

        def changed(*_):
            if not self.syncing:
                self._user_touch(row)
                on_set(row.get_active())
        row.connect('notify::active', changed)

        def sync(snap):
            value = get(snap)
            if value is not None and not self._held(row):
                row.set_active(bool(value))
        self.syncers.append(sync)
        return row

    def combo(self, title, options, get, on_set, subtitle=None):
        row = Adw.ComboRow(title=title, subtitle=subtitle or '',
                           model=Gtk.StringList.new([label for _, label in options]))
        ids = [key for key, _ in options]

        def changed(*_):
            if not self.syncing and row.get_selected() < len(ids):
                self._user_touch(row)
                on_set(ids[row.get_selected()])
        row.connect('notify::selected', changed)

        def sync(snap):
            value = get(snap)
            if value in ids and not self._held(row):
                row.set_selected(ids.index(value))
        self.syncers.append(sync)
        return row

    def scale(self, title, lo, hi, step, get, on_set, fmt='{:.0f}%', subtitle=None, max_fn=None):
        row = Adw.ActionRow(title=title, subtitle=subtitle or '')
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        scale.set_hexpand(True)
        scale.set_size_request(220, -1)
        scale.set_draw_value(False)
        scale.set_valign(Gtk.Align.CENTER)
        label = Gtk.Label(width_chars=5, xalign=1)
        label.add_css_class('numeric')
        label.add_css_class('dim-label')
        row.add_suffix(scale)
        row.add_suffix(label)
        pending = {'id': 0}

        def snap_to_step(value):
            return round(value / step) * step

        def send():
            pending['id'] = 0
            on_set(int(snap_to_step(scale.get_value())))
            return GLib.SOURCE_REMOVE

        def changed(*_):
            label.set_label(fmt.format(snap_to_step(scale.get_value())))
            if self.syncing:
                return
            self._user_touch(scale)
            if pending['id']:
                GLib.source_remove(pending['id'])
            pending['id'] = GLib.timeout_add(180, send)
        scale.connect('value-changed', changed)

        def sync(snap):
            if max_fn:
                top = max_fn(snap)
                if top and scale.get_adjustment().get_upper() != top:
                    scale.get_adjustment().set_upper(top)
            value = get(snap)
            if value is not None and not self._held(scale):
                scale.set_value(value)
                label.set_label(fmt.format(value))
        self.syncers.append(sync)
        return row

    def spin(self, title, lo, hi, step, get, on_set, subtitle=None):
        row = Adw.SpinRow.new_with_range(lo, hi, step)
        row.set_title(title)
        if subtitle:
            row.set_subtitle(subtitle)
        pending = {'id': 0}

        def send():
            pending['id'] = 0
            on_set(int(row.get_value()))
            return GLib.SOURCE_REMOVE

        def changed(*_):
            if self.syncing:
                return
            self._user_touch(row)
            if pending['id']:
                GLib.source_remove(pending['id'])
            pending['id'] = GLib.timeout_add(400, send)
        row.connect('notify::value', changed)

        def sync(snap):
            value = get(snap)
            if value is not None and not self._held(row):
                row.set_value(value)
        self.syncers.append(sync)
        return row

    def info(self, title, get):
        # The "property" style used by GNOME Settings' About pages.
        row = Adw.ActionRow(title=title, subtitle_selectable=True, css_classes=['property'])
        self.syncers.append(lambda snap: row.set_subtitle(GLib.markup_escape_text(str(get(snap) or '—'))))
        return row

    def visible_when(self, widget, predicate):
        self.syncers.append(lambda snap: widget.set_visible(bool(predicate(snap))))
        return widget


def button_row(title, label, callback, subtitle=None, style=None):
    row = Adw.ActionRow(title=title, subtitle=subtitle or '')
    button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    if style:
        button.add_css_class(style)
    button.connect('clicked', lambda *_: callback())
    row.add_suffix(button)
    row.set_activatable_widget(button)
    return row


def group(title=None, description=None, *rows):
    g = Adw.PreferencesGroup(title=title or '', description=description or '')
    for row in rows:
        g.add(row)
    return g


def draw_sweep(area, cr, width, height, sweep):
    """Range-calibration coverage: rim, reach so far (filled), live stick position."""
    import math
    fg = area.get_color()
    accent = Adw.StyleManager.get_default().get_accent_color_rgba()
    cx, cy = width / 2, height / 2
    radius = min(width, height) / 2 - 8
    cr.set_line_width(1.5)
    for scale, alpha in ((1.0, 0.35), (0.66, 0.15)):
        cr.set_source_rgba(fg.red, fg.green, fg.blue, alpha)
        cr.arc(cx, cy, radius * scale, 0, 2 * math.pi)
        cr.stroke()
    for index, reach in enumerate(sweep.sectors):
        angle = ((index + 0.5) / SWEEP_SECTORS) * 2 * math.pi - math.pi
        x, y = cx + math.cos(angle) * reach * radius, cy + math.sin(angle) * reach * radius
        cr.line_to(x, y) if index else cr.move_to(x, y)
    cr.close_path()
    cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.35)
    cr.fill()
    # Directional credit as two thin arcs just outside the rim: inner = clockwise, outer = counterclockwise.
    for ring, done in ((radius + 3, sweep.cw), (radius + 6, sweep.ccw)):
        for index, ok in enumerate(done):
            if ok:
                start = (index / SWEEP_SECTORS) * 2 * math.pi - math.pi
                cr.set_source_rgba(accent.red, accent.green, accent.blue, 1)
                cr.arc(cx, cy, ring, start, start + 2 * math.pi / SWEEP_SECTORS)
                cr.stroke()
    cr.set_source_rgba(fg.red, fg.green, fg.blue, 1)
    cr.arc(cx + sweep.x * radius, cy + sweep.y * radius, 5, 0, 2 * math.pi)
    cr.fill()


class TriggerEditor:
    """One Trigger Lab side: preset, effect type, native-range parameters, zones, bytes, apply."""

    PARAMS = {
        'resistance': [('start', 'Start Position', 0, 255), ('force', 'Force', 0, 255)],
        'weapon': [('start', 'Start Position', 0, 255), ('end', 'Release Position', 0, 255),
                   ('force', 'Force', 0, 255)],
        'auto': [('start', 'Start Position', 0, 255), ('force', 'Strength', 0, 255),
                 ('frequency', 'Frequency', 0, TRIGGER_FREQUENCY_MAX)],
        'zoned-weapon': [('start', 'Start Zone', 0, TRIGGER_ZONES - 1), ('end', 'Release Zone', 0, TRIGGER_ZONES - 1),
                         ('force', 'Force', 0, TRIGGER_ZONE_FORCE_MAX)],
        'zoned-vibration': [('frequency', 'Frequency', 0, TRIGGER_ZONE_FREQUENCY_MAX)],
    }

    def __init__(self, window, title, draft_key, send_side):
        self.w = window
        self.key = draft_key
        self.side = send_side
        self.loading = False
        self.group = Adw.PreferencesGroup(title=title)
        self.dynamic = []

        self.preset = Adw.ComboRow(title='Preset')
        self.preset.connect('notify::selected', self._on_preset)
        menu = Gio.Menu()
        prefix = f'lab-{send_side}'
        for name, label, fn in (('save', 'Save as New Preset…', self._save_preset),
                                ('rename', 'Rename…', self._rename_preset),
                                ('delete', 'Delete…', self._delete_preset)):
            menu.append(label, f'{prefix}.{name}')
        actions = Gio.SimpleActionGroup()
        for name, fn in (('save', self._save_preset), ('rename', self._rename_preset), ('delete', self._delete_preset)):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, fn=fn: fn())
            actions.add_action(action)
        window.insert_action_group(prefix, actions)
        self.preset.add_suffix(Gtk.MenuButton(icon_name='view-more-symbolic', menu_model=menu, valign=Gtk.Align.CENTER,
                                              css_classes=['flat'], tooltip_text='Preset Actions'))

        self.kind = Adw.ComboRow(title='Effect', model=Gtk.StringList.new([l for _, l in TRIGGER_EFFECT_TYPES]))
        self.kind.connect('notify::selected', self._on_kind)
        self.bytes = Adw.ActionRow(title='Bytes Sent to the Controller', css_classes=['property'],
                                   subtitle_selectable=True)
        actions_row = Adw.ActionRow(title='Send to Controller')
        off = Gtk.Button(label='Turn Off', valign=Gtk.Align.CENTER)
        off.connect('clicked', lambda *_: self.w._send_trigger(self.side, {'type': 'off'}))
        apply = Gtk.Button(label='Apply', valign=Gtk.Align.CENTER, css_classes=['suggested-action'])
        apply.connect('clicked', lambda *_: self.w._send_trigger(self.side, self.effect))
        actions_row.add_suffix(off)
        actions_row.add_suffix(apply)
        for row in (self.preset, self.kind):
            self.group.add(row)
        self.tail = [self.bytes, actions_row]
        for row in self.tail:
            self.group.add(row)

    @property
    def effect(self):
        return self.w.lab['drafts'][self.key]

    def _set_effect(self, effect):
        self.w.lab['drafts'][self.key] = effect
        if self.side == 'both':
            self.w.lab['drafts']['r2'] = json.loads(json.dumps(effect))
        self.w._save_lab()
        self._update_bytes()
        self._sync_preset()

    def _presets(self):
        return [{'id': 'default', 'name': 'Default', 'effect': TRIGGER_DEFAULT_EFFECT}] + self.w.lab['profiles']

    def _sync_preset(self):
        self.loading = True
        presets = self._presets()
        names = [p['name'] for p in presets]
        match = next((i for i, p in enumerate(presets) if p['effect'] == self.effect), None)
        if match is None:
            names.append('Custom')
            match = len(names) - 1
        self.preset.set_model(Gtk.StringList.new(names))
        self.preset.set_selected(match)
        self.loading = False

    def _on_preset(self, *_):
        presets = self._presets()
        index = self.preset.get_selected()
        if self.loading or index >= len(presets):
            return
        self._set_effect(json.loads(json.dumps(presets[index]['effect'])))
        self.load()

    def _current_custom(self):
        index = self.preset.get_selected()
        presets = self._presets()
        return presets[index] if 0 < index < len(presets) else None

    def _save_preset(self):
        def save(name):
            self.w.lab['profiles'].append({'id': new_id('trigger'), 'name': name,
                                           'effect': json.loads(json.dumps(self.effect))})
            self.w._save_lab()
            self._refresh_all()
        self.w._ask_name('New Trigger Preset', '', 'Save', save)

    def _rename_preset(self):
        preset = self._current_custom()
        if not preset:
            self.w.toast('Choose a saved preset to rename')
            return

        def rename(name):
            preset['name'] = name
            self.w._save_lab()
            self._refresh_all()
        self.w._ask_name('Rename Preset', preset['name'], 'Rename', rename)

    def _delete_preset(self):
        preset = self._current_custom()
        if not preset:
            self.w.toast('Choose a saved preset to delete')
            return

        def delete():
            self.w.lab['profiles'] = [p for p in self.w.lab['profiles'] if p['id'] != preset['id']]
            self.w._save_lab()
            self._refresh_all()
        self.w._confirm(f'Delete “{preset["name"]}”?', 'This trigger preset will be removed.', 'Delete', delete)

    def _refresh_all(self):
        for editor in self.w.trigger_editors.values():
            editor._sync_preset()

    def _on_kind(self, *_):
        if self.loading:
            return
        kind = TRIGGER_EFFECT_TYPES[self.kind.get_selected()][0]
        if kind != self.effect['type']:
            self._set_effect(default_trigger_effect(kind))
            self.load()

    def _update_bytes(self):
        self.bytes.set_subtitle('<tt>' + ' '.join(f'{b:02x}' for b in encode_trigger_effect(self.effect)) + '</tt>')

    def load(self):
        """Rebuild the parameter rows for the current draft."""
        self.loading = True
        effect = self.effect
        self.kind.set_selected([k for k, _ in TRIGGER_EFFECT_TYPES].index(effect['type']))
        for row in self.dynamic + self.tail:
            self.group.remove(row)
        self.dynamic = []
        for field, title, lo, hi in self.PARAMS.get(effect['type'], []):
            row = Adw.SpinRow.new_with_range(lo, hi, 1)
            row.set_title(title)
            row.set_value(effect.get(field, lo))

            def changed(r, _p, f=field):
                if not self.loading:
                    self._set_effect({**self.effect, f: int(r.get_value())})
            row.connect('notify::value', changed)
            self.dynamic.append(row)
        if 'zones' in effect:
            self.dynamic.append(self._zones_row(effect))
        for row in self.dynamic + self.tail:
            self.group.add(row)
        self._update_bytes()
        self.loading = False
        self._sync_preset()

    def _zones_row(self, effect):
        """Ten vertical sliders, travel from left (start) to right (end). Bottom notch = zone off."""
        row = Adw.PreferencesRow(activatable=False, focusable=False)
        box = Gtk.Box(spacing=4, homogeneous=True, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        title = Gtk.Label(label='Zones', xalign=0, css_classes=['dim-label', 'caption'])
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.append(title)
        title.set_margin_start(12)
        title.set_margin_top(8)
        for zone in range(TRIGGER_ZONES):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            value_label = Gtk.Label(css_classes=['numeric', 'caption'])
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -1, TRIGGER_ZONE_FORCE_MAX, 1)
            scale.set_inverted(True)
            scale.set_draw_value(False)
            scale.set_size_request(-1, 120)
            scale.set_halign(Gtk.Align.CENTER)
            level = effect['zones'][zone]
            scale.set_value(-1 if level is None else level)
            value_label.set_label('–' if level is None else str(level))

            def moved(s, z=zone, lab=value_label):
                v = int(round(s.get_value()))
                lab.set_label('–' if v < 0 else str(v))
                if self.loading:
                    return
                zones = list(self.effect['zones'])
                zones[z] = None if v < 0 else v
                self._set_effect({**self.effect, 'zones': zones})
            scale.connect('value-changed', moved)
            column.append(value_label)
            column.append(scale)
            column.append(Gtk.Label(label=str(zone + 1), css_classes=['dim-label', 'caption']))
            box.append(column)
        outer.append(box)
        hint = Gtk.Label(label='Bottom position turns a zone off; 0–7 is its strength.', wrap=True, xalign=0,
                         css_classes=['dim-label', 'caption'], margin_start=12, margin_bottom=10)
        outer.append(hint)
        row.set_child(outer)
        return row


TESTER_BUTTONS = [
    ('triangle', 'Triangle', 'Triangle'), ('circle', 'Circle', 'Circle'), ('cross', 'Cross', 'Cross'),
    ('square', 'Square', 'Square'), ('dpadUp', 'Up', 'D-Pad Up'), ('dpadRight', 'Right', 'D-Pad Right'),
    ('dpadDown', 'Down', 'D-Pad Down'), ('dpadLeft', 'Left', 'D-Pad Left'), ('l1', 'L1', 'L1'), ('r1', 'R1', 'R1'),
    ('l2Pressed', 'L2', 'L2'), ('r2Pressed', 'R2', 'R2'), ('l3', 'L3', 'Left Stick Click'),
    ('r3', 'R3', 'Right Stick Click'), ('create', 'Create', 'Create'), ('options', 'Options', 'Options'),
    ('home', 'PS', 'Home'), ('touchpadButton', 'Touchpad', 'Touch Pad Press'), ('mute', 'Mute', None),
]
TESTER_EDGE_BUTTONS = [('edgeLeftFunction', 'LFN'), ('edgeRightFunction', 'RFN'), ('edgeLeftPaddle', 'LB'),
                       ('edgeRightPaddle', 'RB')]
TESTER_POLL_MS = 40


def _draw_stick(area, cr, width, height, data):
    import math
    fg = area.get_color()
    accent = Adw.StyleManager.get_default().get_accent_color_rgba()
    cx, cy, radius = width / 2, height / 2, min(width, height) / 2 - 6
    cr.set_line_width(1.5)
    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.3)
    cr.arc(cx, cy, radius, 0, 2 * math.pi)
    cr.stroke()
    cr.move_to(cx - radius, cy)
    cr.line_to(cx + radius, cy)
    cr.move_to(cx, cy - radius)
    cr.line_to(cx, cy + radius)
    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.12)
    cr.stroke()
    deadzone = data.get('deadzone', 0) / 100
    if deadzone:
        cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.18)
        cr.arc(cx, cy, radius * deadzone, 0, 2 * math.pi)
        cr.fill()
    x, y = (data.get('x', 128) - 128) / 127, (data.get('y', 128) - 128) / 127
    cr.set_source_rgba(accent.red, accent.green, accent.blue, 1 if data.get('pressed') else 0.9)
    cr.arc(cx + x * radius, cy + y * radius, 9 if data.get('pressed') else 6, 0, 2 * math.pi)
    cr.fill()


def _draw_trigger(area, cr, width, height, data):
    fg = area.get_color()
    accent = Adw.StyleManager.get_default().get_accent_color_rgba()
    value = data.get('value', 0) / 255
    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.12)
    cr.rectangle(0, 0, width, height)
    cr.fill()
    cr.set_source_rgba(accent.red, accent.green, accent.blue, 1)
    cr.rectangle(0, height * (1 - value), width, height * value)
    cr.fill()


def _draw_touchpad(area, cr, width, height, data):
    fg = area.get_color()
    accent = Adw.StyleManager.get_default().get_accent_color_rgba()
    import math
    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.08)
    cr.rectangle(0, 0, width, height)
    cr.fill()
    for point in data.get('points', []):
        if point.get('active'):
            cr.set_source_rgba(accent.red, accent.green, accent.blue, 1)
            cr.arc(point['x'] / 1920 * width, point['y'] / 1080 * height, 8, 0, 2 * math.pi)
            cr.fill()


class TesterWindow(Adw.Window):
    """Live input tester (upstream TesterApp): a separate window, so it can stay in view while you play.
    Polling and the input hold only run while it is open."""

    def __init__(self, main):
        super().__init__(title='Input Tester', default_width=760, default_height=860, transient_for=None)
        self.main = main
        self.daemon = main.daemon
        self.busy = False
        self.hold_id = 0
        self.direct_paths = []
        self.data = {k: {} for k in ('left', 'right', 'l2', 'r2', 'touch')}

        page = Adw.PreferencesPage()
        self.source = Adw.ComboRow(title='Read From')
        self.source.connect('notify::selected', self._on_source)
        self.pause = Adw.SwitchRow(title='Pause Input to This Computer', active=True,
                                   subtitle='Buttons you press here do not reach games or the desktop')
        self.pause.connect('notify::active', lambda *_: self._update_hold())
        self.status = Adw.ActionRow(title='Status', css_classes=['property'], subtitle='Waiting for input…')
        page.add(group(None, None, self.source, self.pause, self.status))

        self.chips = {}
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=10, min_children_per_line=4,
                           row_spacing=6, column_spacing=6, homogeneous=True, margin_top=6, margin_bottom=6)
        for key, label, glyph in TESTER_BUTTONS:
            flow.append(self._chip(key, label, glyph))
        self.edge_chips = []
        for key, label in TESTER_EDGE_BUTTONS:
            chip = self._chip(key, label, None, text=label)
            self.edge_chips.append(chip)
            flow.append(chip)
        page.add(group('Buttons', 'Lights up while pressed.', flow))

        analog = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
        self.areas = {}
        for key, title, draw, size in (('l2', 'L2', _draw_trigger, (22, 150)), ('left', 'Left Stick', _draw_stick, (150, 150)),
                                       ('right', 'Right Stick', _draw_stick, (150, 150)), ('r2', 'R2', _draw_trigger, (22, 150))):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            area = Gtk.DrawingArea(content_width=size[0], content_height=size[1], halign=Gtk.Align.CENTER)
            area.set_draw_func(lambda a, cr, w, h, k=key, d=draw: d(a, cr, w, h, self.data[k]))
            value = Gtk.Label(css_classes=['numeric', 'caption', 'dim-label'])
            column.append(area)
            column.append(Gtk.Label(label=title, css_classes=['caption-heading']))
            column.append(value)
            analog.append(column)
            self.areas[key] = (area, value)
        page.add(group('Sticks and Triggers', 'The shaded circle is the deadzone the bridge applies.', analog))

        touch = Gtk.DrawingArea(content_width=384, content_height=216, halign=Gtk.Align.CENTER, margin_top=6,
                                margin_bottom=6)
        touch.set_draw_func(lambda a, cr, w, h: _draw_touchpad(a, cr, w, h, self.data['touch']))
        self.areas['touch'] = (touch, None)
        page.add(group('Touchpad', None, touch))

        self.facts = {}
        motion = group('Motion')
        status = group('Controller')
        for grp, items in ((motion, ('Gyroscope', 'Acceleration')),
                           (status, ('Battery', 'Charging', 'Headset', 'Microphone'))):
            for title in items:
                row = Adw.ActionRow(title=title, css_classes=['property'], subtitle='—')
                self.facts[title] = row
                grp.add(row)
        page.add(motion)
        page.add(status)
        self.raw = Gtk.Label(wrap=True, xalign=0, selectable=True, css_classes=['monospace', 'caption'],
                             margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        raw_row = Adw.PreferencesRow(activatable=False, child=self.raw)
        page.add(group('Raw Input Report', 'Exactly what the bridge forwarded; everything above is decoded from it.',
                       raw_row))

        view = Adw.ToolbarView(content=page)
        view.add_top_bar(Adw.HeaderBar())
        self.set_content(view)
        self._fill_sources(main.snapshot)
        self.poll_id = GLib.timeout_add(TESTER_POLL_MS, self._tick)
        self.snap_id = main.daemon.connect('snapshot', lambda _d, s: self._fill_sources(s))
        self.connect('close-request', self._on_close)
        self._update_hold()

    def _chip(self, key, label, glyph, text=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=['ds5-chip'])
        if glyph:
            box.append(glyph_picture(glyph, 28))
        elif key == 'mute':
            box.append(Gtk.Image(icon_name='microphone-sensitivity-muted-symbolic', pixel_size=24))
        else:
            pill = Gtk.Label(label=text, css_classes=['caption-heading'], height_request=28)
            box.append(pill)
        box.append(Gtk.Label(label=label, css_classes=['caption']))
        self.chips[key] = box
        return box

    def _fill_sources(self, snap):
        census = (snap or {}).get('bridgeDevices') or {}
        direct = [c for c in census.get('directControllers', []) if not c.get('hidUnavailable')]
        paths = [None] + [c['path'] for c in direct]
        labels = ['Bridge'] + [f'USB · {(c.get("product") or "DualSense").replace("Sony Interactive Entertainment ", "")}'
                               + (' (charging via bridge)' if c.get('chargingViaBridge') else '') for c in direct]
        selected = next((c['path'] for c in direct if c.get('selectedForTester')), None)
        if paths != self.direct_paths:
            self.direct_paths = paths
            self._loading = True
            self.source.set_model(Gtk.StringList.new(labels))
            self._loading = False
        self._loading = True
        self.source.set_selected(paths.index(selected) if selected in paths else 0)
        self._loading = False
        self.source.set_visible(len(paths) > 1)
        edge = self.main._is_edge(snap or {})
        for chip in self.edge_chips:
            chip.get_parent().set_visible(edge)
        dz = (snap or {}).get('settings', {})
        self.data['left']['deadzone'] = dz.get('stickDeadzoneLeftPercent', 0)
        self.data['right']['deadzone'] = dz.get('stickDeadzoneRightPercent', 0)

    def _direct(self):
        index = self.source.get_selected()
        return self.direct_paths[index] if 0 < index < len(self.direct_paths) else None

    def _on_source(self, *_):
        if getattr(self, '_loading', False):
            return
        self.daemon.call('bridge:selectTesterController', self._direct())
        self._update_hold()

    def _update_hold(self):
        # A USB controller reaches the computer through the system driver, which cannot be paused.
        direct = self._direct() is not None
        self.pause.set_sensitive(not direct)
        on = self.pause.get_active() and not direct
        if self.hold_id:
            GLib.source_remove(self.hold_id)
            self.hold_id = 0
        if on:
            renew = lambda: (self.daemon.call('bridge:holdInputForwarding', INPUT_HOLD_MS, quiet=True), True)[1]  # noqa: E731
            renew()
            self.hold_id = GLib.timeout_add(INPUT_HOLD_RENEW_MS, renew)
        else:
            self.daemon.call('bridge:holdInputForwarding', 0, quiet=True)

    def _tick(self):
        if self.busy:
            return GLib.SOURCE_CONTINUE
        self.busy = True
        started = GLib.get_monotonic_time()

        def got(snapshot):
            self.busy = False
            self._show(snapshot, (GLib.get_monotonic_time() - started) / 1000)

        def failed(message):
            self.busy = False
            self.status.set_subtitle(message)
        self.daemon.call('bridge:readControllerInput', done=got, fail=failed)
        return GLib.SOURCE_CONTINUE

    def _show(self, snapshot, ms):
        state = (snapshot or {}).get('state')
        if not state:
            self.status.set_subtitle('No controller is sending input' if self._direct() else
                                     'No controller connected to the bridge')
            return
        self.status.set_subtitle(f'Live — {ms:.0f} ms per read, every {TESTER_POLL_MS} ms')
        for key, chip in self.chips.items():
            pressed = bool(state.get(key))
            (chip.add_css_class if pressed else chip.remove_css_class)('pressed')
        self.data['left'].update(x=state['leftStickX'], y=state['leftStickY'], pressed=state.get('l3'))
        self.data['right'].update(x=state['rightStickX'], y=state['rightStickY'], pressed=state.get('r3'))
        self.data['l2']['value'] = state['leftTrigger']
        self.data['r2']['value'] = state['rightTrigger']
        self.data['touch']['points'] = state.get('touchPoints', [])
        labels = {'left': f'{state["leftStickX"]}, {state["leftStickY"]}',
                  'right': f'{state["rightStickX"]}, {state["rightStickY"]}',
                  'l2': str(state['leftTrigger']), 'r2': str(state['rightTrigger'])}
        for key, (area, value) in self.areas.items():
            area.queue_draw()
            if value:
                value.set_label(labels[key])
        self.facts['Gyroscope'].set_subtitle(f'{state["gyroX"]}  {state["gyroY"]}  {state["gyroZ"]}')
        self.facts['Acceleration'].set_subtitle(f'{state["accelX"]}  {state["accelY"]}  {state["accelZ"]}')
        battery = state.get('batteryPercent')
        self.facts['Battery'].set_subtitle('Unknown' if battery is None else f'{battery}%')
        self.facts['Charging'].set_subtitle('Yes' if state.get('charging') else 'No')
        self.facts['Headset'].set_subtitle('Plugged In' if state.get('headsetPlugged') else 'Not Connected')
        mic = 'Plugged In' if state.get('microphonePlugged') else 'Built-In'
        self.facts['Microphone'].set_subtitle(mic + (' · Muted' if state.get('microphoneMuted') else ''))
        self.raw.set_label(' '.join(f'{b:02x}' for b in snapshot.get('raw', [])) or '—')

    def _on_close(self, *_):
        GLib.source_remove(self.poll_id)
        if self.hold_id:
            GLib.source_remove(self.hold_id)
        self.daemon.call('bridge:holdInputForwarding', 0, quiet=True)
        if self._direct():
            self.daemon.call('bridge:selectTesterController', None, quiet=True)
        self.daemon.disconnect(self.snap_id)
        self.main.tester = None
        return False


# ----------------------------------------------------------------- window

class Window(Adw.ApplicationWindow):
    def __init__(self, app, daemon):
        super().__init__(application=app, title='DS5 Bridge', default_width=980, default_height=720)
        self.set_size_request(360, 400)
        self.daemon = daemon
        self.snapshot = None
        self.local = LocalState()
        self.b = Binder(self)

        self.toasts = Adw.ToastOverlay()
        self.banner = Adw.Banner()
        self.banner.connect('button-clicked', lambda *_: self._banner_action())
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)

        self.pages = [
            ('controller', 'Controller', 'input-gaming-symbolic', self._page_controller),
            ('devices', 'Devices', 'bluetooth-symbolic', self._page_devices),
            ('audio', 'Audio', 'audio-speakers-symbolic', self._page_audio),
            ('haptics', 'Haptics', 'weather-storm-symbolic', self._page_haptics),
            ('triggers', 'Triggers', 'glyph:R2', self._page_triggers),
            ('sticks', 'Sticks', 'glyph:Left Stick', self._page_sticks),
            ('lighting', 'Lighting', 'display-brightness-symbolic', self._page_lighting),
            ('buttons', 'Buttons', 'input-keyboard-symbolic', self._page_buttons),
            ('remapping', 'Remapping', 'media-playlist-shuffle-symbolic', self._page_remapping),
            ('chords', 'Chords', 'input-dialpad-symbolic', self._page_chords),
            ('system', 'System', 'emblem-system-symbolic', self._page_system),
        ]

        sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        sidebar.add_css_class('navigation-sidebar')
        for key, title, icon, build in self.pages:
            page = build()
            self.stack.add_named(page, key)
            box = Gtk.Box(spacing=12)
            box.append(glyph_picture(icon[6:], 16, crop=True) if icon.startswith('glyph:') else Gtk.Image(icon_name=icon))
            box.append(Gtk.Label(label=title, xalign=0))
            row = Gtk.ListBoxRow(child=box)
            row._key, row._title = key, title
            sidebar.append(row)
        sidebar.connect('row-activated', self._on_sidebar)

        menu = Gio.Menu()
        menu.append('Input Tester', 'win.tester')
        menu.append('Classic Interface', 'app.classic')
        menu.append('Restore Defaults…', 'win.restore-defaults')
        menu.append('About DS5 Bridge', 'app.about')
        side_header = Adw.HeaderBar()
        side_header.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu,
                                            primary=True, tooltip_text='Main Menu'))
        side_view = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=sidebar))
        side_view.add_top_bar(side_header)
        self.sidebar_page = Adw.NavigationPage(title='DS5 Bridge', child=side_view)

        content_view = Adw.ToolbarView(content=self.toasts)
        content_view.add_top_bar(Adw.HeaderBar())
        content_view.add_top_bar(self.banner)
        self.toasts.set_child(self.stack)
        self.content_page = Adw.NavigationPage(title='Controller', child=content_view)

        self.split = Adw.NavigationSplitView(sidebar=self.sidebar_page, content=self.content_page,
                                             min_sidebar_width=220, max_sidebar_width=260)
        self.set_content(self.split)
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 640sp'))
        breakpoint.add_setter(self.split, 'collapsed', True)
        self.add_breakpoint(breakpoint)

        self.tester = None
        tester = Gio.SimpleAction.new('tester', None)
        tester.connect('activate', lambda *_: self.open_tester())
        self.add_action(tester)
        restore = Gio.SimpleAction.new('restore-defaults', None)
        restore.connect('activate', lambda *_: self._restore_defaults())
        self.add_action(restore)

        sidebar.select_row(sidebar.get_row_at_index(0))
        daemon.connect('snapshot', lambda _d, snap: self._on_snapshot(snap))
        daemon.connect('available', lambda _d, ok: self._update_banner())
        daemon.connect('error', lambda _d, msg: self.toast(msg))
        daemon.refresh()

    # ---- plumbing

    def call(self, channel, *args, **kw):
        self.daemon.call(channel, *args, **kw)

    def setter(self, channel):
        return lambda value: self.call(channel, value)

    def open_tester(self):
        if not self.tester:
            self.tester = TesterWindow(self)
            self.tester.set_application(self.get_application())
        self.tester.present()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def _on_sidebar(self, _box, row):
        self.stack.set_visible_child_name(row._key)
        self.content_page.set_title(row._title)
        self.split.set_show_content(True)

    def _on_snapshot(self, snap):
        if not snap:
            return
        self.snapshot = snap
        self.b.sync(snap)
        self._update_banner()

    def _update_banner(self):
        snap = self.snapshot
        if not self.daemon.running:
            self.banner.set_title('The DS5 Bridge service is not running')
            self.banner.set_button_label('Start')
            self.banner.set_revealed(True)
        elif snap and snap.get('state') in ('no-bridge', 'error', 'incompatible'):
            self.banner.set_title(snap.get('message') or 'Bridge not found')
            self.banner.set_button_label('Retry')
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

    def _banner_action(self):
        if not self.daemon.running:
            # D-Bus activation starts ds5-bridged.service.
            self.daemon.refresh()
        else:
            self.call('bridge:refreshBridgeDevices')

    def _confirm(self, heading, body, label, callback, destructive=True):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('ok', label)
        dialog.set_response_appearance(
            'ok', Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('cancel')
        dialog.connect('response', lambda _d, r: r == 'ok' and callback())
        dialog.present(self)

    def _ask_name(self, heading, initial, label, callback):
        dialog = Adw.AlertDialog(heading=heading)
        entry = Gtk.Entry(text=initial or '', activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('ok', label)
        dialog.set_response_appearance('ok', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('ok')
        dialog.connect('response', lambda _d, r: r == 'ok' and entry.get_text().strip()
                       and callback(entry.get_text().strip()))
        dialog.present(self)

    def _restore_defaults(self):
        self._confirm('Restore Defaults?', 'All DS5 Bridge settings go back to their defaults. '
                      'Saved profiles are kept.', 'Restore',
                      lambda: self.call('bridge:restoreDefaults',
                                        done=lambda _: self.toast('Defaults restored')))

    # ---- pages

    def _page(self, *groups):
        page = Adw.PreferencesPage()
        for g in groups:
            page.add(g)
        return page

    def _profile_row(self, title, subtitle, list_key, selected_key, prefix, select, save, update, rename, delete,
                     reset=None):
        """ComboRow over a profile list with a ⋮ menu: save new, update, rename, delete (and reset)."""
        b = self.b
        ids = []
        row = Adw.ComboRow(title=title, subtitle=subtitle, model=Gtk.StringList())

        def changed(*_):
            if not b.syncing and row.get_selected() < len(ids):
                self.call(select, ids[row.get_selected()])
        row.connect('notify::selected', changed)

        def sync(s):
            items = dig(s, f'settings.{list_key}', []) or []
            names = [p['name'] for p in items]
            model = row.get_model()
            if [p['id'] for p in items] != ids or names != [model.get_string(i) for i in range(model.get_n_items())]:
                ids[:] = [p['id'] for p in items]
                row.set_model(Gtk.StringList.new(names))
            current = dig(s, f'settings.{selected_key}')
            if current in ids:
                row.set_selected(ids.index(current))
        b.syncers.append(sync)

        def current():
            items = dig(self.snapshot, f'settings.{list_key}', []) or []
            i = row.get_selected()
            return items[i] if 0 <= i < len(items) else None

        handlers = {
            'save-new': lambda: self._ask_name('New Profile', '', 'Save', lambda n: self.call(save, n)),
            'update': lambda: (p := current()) and self.call(update, p['id'], done=lambda _: self.toast(f'“{p["name"]}” updated')),
            'rename': lambda: (p := current()) and self._ask_name(
                'Rename Profile', p['name'], 'Rename', lambda n: self.call(rename, p['id'], n)),
            'delete': lambda: (p := current()) and self._confirm(
                f'Delete “{p["name"]}”?', 'This profile will be removed permanently.', 'Delete',
                lambda: self.call(delete, p['id'])),
        }
        if reset:
            handlers['reset'] = lambda: self._confirm(
                'Reset All Buttons?', 'Every button goes back to its normal function.', 'Reset', lambda: self.call(reset))
        actions = Gio.SimpleActionGroup()
        for name, fn in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, fn=fn: fn())
            actions.add_action(action)
        self.insert_action_group(prefix, actions)
        menu = Gio.Menu()
        menu.append('Save Current Settings as New Profile…', f'{prefix}.save-new')
        menu.append('Update Profile With Current Settings', f'{prefix}.update')
        section = Gio.Menu()
        section.append('Rename…', f'{prefix}.rename')
        section.append('Delete…', f'{prefix}.delete')
        menu.append_section(None, section)
        if reset:
            tail = Gio.Menu()
            tail.append('Reset All Buttons…', f'{prefix}.reset')
            menu.append_section(None, tail)
        row.add_suffix(Gtk.MenuButton(icon_name='view-more-symbolic', menu_model=menu, valign=Gtk.Align.CENTER,
                                      tooltip_text='Profile Actions', css_classes=['flat']))
        return row

    def _page_controller(self):
        b = self.b
        connected = lambda s: dig(s, 'status.controllerConnected')  # noqa: E731

        # Hero, in the spirit of Settings' device pages.
        # Upstream's DualSense artwork, as on its controller card.
        icon = Gtk.Picture.new_for_filename(CONTROLLER_ART)
        icon.set_can_shrink(True)
        icon.set_content_fit(Gtk.ContentFit.CONTAIN)
        icon.set_size_request(240, 154)
        icon.set_halign(Gtk.Align.CENTER)
        title = Gtk.Label(css_classes=['title-1'])
        subtitle = Gtk.Label(css_classes=['dim-label'])
        level = Gtk.LevelBar(min_value=0, max_value=100, width_request=220, halign=Gtk.Align.CENTER)
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_bottom=12)
        for w in (icon, title, subtitle, level):
            hero.append(w)

        def hero_sync(s):
            st = s.get('status') or {}
            on = bool(st.get('controllerConnected'))
            title.set_label(controller_label(st.get('controllerType')) if on else 'No Controller')
            battery = st.get('batteryPercent')
            charging = st.get('rawPowerState') in (1, 2)
            if not on:
                subtitle.set_label('Turn on a paired controller, or pair one in Devices'
                                   if s.get('state') == 'connected' else (s.get('message') or ''))
            elif battery is None:
                subtitle.set_label('Connected')
            else:
                subtitle.set_label(f'{battery}%' + (' · Charging' if charging else ''))
            level.set_visible(on and battery is not None)
            level.set_value(battery or 0)
            icon.set_opacity(1 if on else 0.5)
        b.syncers.append(hero_sync)

        profiles = self._profile_row(
            'Profile', 'Settings that follow this controller', 'controllerProfiles', 'selectedControllerProfileId',
            prefix='profile', select='bridge:selectControllerProfile', save='bridge:saveControllerProfile',
            update='bridge:updateControllerProfile', rename='bridge:renameControllerProfile',
            delete='bridge:deleteControllerProfile')

        test_row = Adw.ActionRow(title='Test', subtitle='Check that output reaches the controller')
        for label, channel in (('Haptics', 'bridge:testHaptics'), ('Speaker', 'bridge:testSpeaker')):
            button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            button.connect('clicked', lambda _b, c=channel: self.call(c))
            test_row.add_suffix(button)
        b.visible_when(test_row, connected)

        sleep = b.visible_when(button_row('Turn Off Controller', 'Turn Off', lambda: self.call('bridge:sleepController')),
                               connected)

        return self._page(
            group(None, None, hero),
            group(None, None, profiles,
                  b.combo('Emulated Controller', PERSONAS, lambda s: dig(s, 'settings.hostPersonaMode'),
                          self.setter('bridge:setHostPersonaMode'),
                          subtitle='What the computer sees the bridge as')),
            group(None, None, test_row, sleep),
            group('Bridge', None,
                  b.info('Status', lambda s: s.get('message')),
                  b.info('Firmware', lambda s: dig(s, 'status.firmwareVersion')),
                  b.info('Protocol', lambda s: dig(s, 'status.protocolVersion')),
                  b.info('Signal', lambda s: (lambda d: f'{d} dBm' if d is not None else None)(
                      dig(s, 'status.signalStrengthDbm')))),
        )

    def _page_devices(self):
        b = self.b
        known = Adw.PreferencesGroup(title='Paired Controllers',
                                     description='Each controller can load its own profile and button layout.')
        known_rows = []
        last = {'key': None}

        def known_sync(s):
            st = s.get('settings', {})
            history = st.get('controllerHistory', []) or []
            key = json.dumps([history, st.get('controllerBindings'), st.get('buttonRemappingBindings'),
                              [(p['id'], p['name']) for p in st.get('controllerProfiles', [])],
                              [(p['id'], p['name']) for p in st.get('buttonRemappingProfiles', [])]])
            if key == last['key']:
                return
            last['key'] = key
            for row in known_rows:
                known.remove(row)
            known_rows.clear()
            if not history:
                row = Adw.ActionRow(title='No controllers yet', subtitle='Pair a controller to see it here')
                known.add(row)
                known_rows.append(row)

            def binding_row(title, profiles, current, channel, mac):
                options = [(None, 'Not Linked')] + [(p['id'], p['name']) for p in profiles]
                row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _, label in options]))
                ids = [k for k, _ in options]
                row.set_selected(ids.index(current) if current in ids else 0)
                row.connect('notify::selected', lambda r: self.call(channel, mac, ids[r.get_selected()]))
                return row

            for entry in history:
                mac = ':'.join(entry['mac'][i:i + 2] for i in range(0, len(entry['mac']), 2)).upper()
                seen = GLib.DateTime.new_from_unix_local(entry['lastSeenAt'] // 1000).format('%x %X')
                bits = [mac, f'last seen {seen}']
                if entry.get('lastBatteryPercent') is not None:
                    bits.append(f'{entry["lastBatteryPercent"]}%')
                row = Adw.ExpanderRow(title=controller_label(entry.get('controllerType')), subtitle=' · '.join(bits))
                row.add_prefix(Gtk.Image(icon_name='input-gaming-symbolic'))
                forget = Gtk.Button(icon_name='user-trash-symbolic', valign=Gtk.Align.CENTER,
                                    tooltip_text='Forget Controller', css_classes=['flat'])
                forget.connect('clicked', lambda _b, m=entry['mac'], label=mac: self._confirm(
                    f'Forget {label}?', 'The controller will need to be paired again.', 'Forget',
                    lambda: self.call('bridge:forgetControllerPairing', m)))
                row.add_suffix(forget)
                row.add_row(binding_row('Profile', st.get('controllerProfiles', []),
                                        (st.get('controllerBindings') or {}).get(entry['mac']),
                                        'bridge:setControllerBinding', entry['mac']))
                row.add_row(binding_row('Remapping Profile', st.get('buttonRemappingProfiles', []),
                                        (st.get('buttonRemappingBindings') or {}).get(entry['mac']),
                                        'bridge:setButtonRemappingBinding', entry['mac']))
                known.add(row)
                known_rows.append(row)
        b.syncers.append(known_sync)

        bridges = Adw.PreferencesGroup(title='Bridges')
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', css_classes=['flat'], tooltip_text='Look for Bridges')
        refresh.connect('clicked', lambda *_: self.call('bridge:refreshBridgeDevices'))
        bridges.set_header_suffix(refresh)
        bridge_rows = []
        output_ids = []
        output = Adw.ComboRow(title='Audio and Haptics Output',
                              subtitle='Where sound and haptics go when a controller is also plugged in by USB')
        output.connect('notify::selected', lambda r, _p: None if b.syncing or r.get_selected() >= len(output_ids)
                       else self.call('bridge:setAudioTarget', output_ids[r.get_selected()]))
        last_bridges = {'key': None}

        def bridges_sync(s):
            census = s.get('bridgeDevices') or {}
            items = census.get('bridges', [])
            direct = [c for c in census.get('directControllers', []) if not c.get('hidUnavailable')]
            key = json.dumps([items, [(c['path'], c.get('product')) for c in direct], census.get('audioTargetPath')])
            if key == last_bridges['key']:
                return
            last_bridges['key'] = key
            for row in bridge_rows:
                bridges.remove(row)
            bridge_rows.clear()
            if not items:
                row = Adw.ActionRow(title='No bridge found', subtitle='Connect the Pico to this computer by USB')
                bridges.add(row)
                bridge_rows.append(row)
            for item in items:
                name = item.get('name') or 'Pico'
                bits = ['Connected' if item.get('connected') else 'Not connected']
                if item.get('selected'):
                    bits.insert(0, 'In use')
                if item.get('uniqueId'):
                    bits.append(item['uniqueId'].upper())
                row = Adw.ActionRow(title=GLib.markup_escape_text(name), subtitle=' · '.join(bits))
                row.add_prefix(Gtk.Image(icon_name='drive-harddisk-usb-symbolic'))
                if item.get('uniqueId'):
                    rename = Gtk.Button(icon_name='document-edit-symbolic', valign=Gtk.Align.CENTER,
                                        css_classes=['flat'], tooltip_text='Rename Bridge')
                    rename.connect('clicked', lambda _b, it=item: self._ask_name(
                        'Rename Bridge', it.get('name') or '', 'Rename',
                        lambda n: self.call('bridge:setBridgeLabel', it['uniqueId'], n)))
                    row.add_suffix(rename)
                if not item.get('selected'):
                    use = Gtk.Button(label='Use', valign=Gtk.Align.CENTER)
                    use.connect('clicked', lambda _b, it=item: self.call('bridge:selectBridge', it['path']))
                    row.add_suffix(use)
                bridges.add(row)
                bridge_rows.append(row)
            output_ids[:] = [None] + [c['path'] for c in direct]
            output.set_model(Gtk.StringList.new(['Bridge'] + [
                f'USB · {(c.get("product") or "DualSense").replace("Sony Interactive Entertainment ", "")}'
                for c in direct]))
            target = census.get('audioTargetPath')
            output.set_selected(output_ids.index(target) if target in output_ids else 0)
            output.set_visible(bool(direct))
            bridges.remove(output)
            bridges.add(output)
        bridges.add(output)
        b.syncers.append(bridges_sync)

        return self._page(
            bridges,
            group('Pairing', 'Hold the PS and Create buttons until the light bar flashes, then pair.',
                  button_row('Pair New Controller', 'Pair', lambda: self.call('bridge:requestControllerPairing'),
                             style='suggested-action'),
                  b.switch('Wake Computer on Connect', lambda s: dig(s, 'settings.wakeOnControllerConnect'),
                           self.setter('bridge:setWakeOnControllerConnect'))),
            known,
            group(None, None, button_row('Forget All Controllers', 'Forget All', lambda: self._confirm(
                'Forget All Controllers?', 'Every controller will need to be paired again.', 'Forget All',
                lambda: self.call('bridge:forgetControllerPairings')), style='destructive-action')),
        )

    def _page_audio(self):
        b = self.b
        return self._page(
            group('Speaker', None,
                  b.switch('Speaker', lambda s: dig(s, 'settings.speakerEnabled'), self.setter('bridge:setSpeakerEnabled')),
                  b.scale('Volume', 0, 100, 10, lambda s: dig(s, 'settings.speakerVolumePercent'),
                          self.setter('bridge:setSpeakerVolume')),
                  b.spin('Amplifier Gain', 1, 7, 1, lambda s: dig(s, 'settings.speakerGainLevel'),
                         self.setter('bridge:setSpeakerGainLevel'), subtitle='Higher is louder, with more distortion'),
                  b.switch('Volume Shortcut', lambda s: dig(s, 'settings.speakerVolumeShortcutEnabled'),
                           self.setter('bridge:setSpeakerVolumeShortcutEnabled'),
                           subtitle='Change speaker volume from the controller'),
                  button_row('Test Speaker', 'Play', lambda: self.call('bridge:testSpeaker'))),
            group('Microphone', None,
                  b.switch('Microphone', lambda s: not dig(s, 'settings.micMuted', False),
                           lambda on: self.call('bridge:setMicMute', not on)),
                  b.scale('Volume', 0, 100, 10, lambda s: dig(s, 'settings.micVolumePercent'),
                          self.setter('bridge:setMicVolume')),
                  b.switch('Full-Duplex Microphone', lambda s: dig(s, 'settings.duplexMicEnabled'),
                           self.setter('bridge:setDuplexMicEnabled'),
                           subtitle='Keep the microphone open while the speaker plays')),
        )

    def _page_haptics(self):
        b = self.b
        feedback_max = lambda s: BOOSTED_FEEDBACK_MAX if dig(s, 'settings.feedbackBoostEnabled') \
            else STANDARD_FEEDBACK_MAX  # noqa: E731

        def reactive(key):
            return lambda value: self.call('bridge:setAudioReactiveHapticsConfig', {key: value})

        expander = Adw.ExpanderRow(title='Audio-Reactive Haptics', subtitle='Turn sound into vibration',
                                   show_enable_switch=True)

        def expander_changed(*_):
            if not b.syncing:
                b._user_touch(expander)
                reactive('enabled')(expander.get_enable_expansion())
        expander.connect('notify::enable-expansion', expander_changed)
        b.syncers.append(lambda s: None if b._held(expander) else expander.set_enable_expansion(
            bool(dig(s, 'settings.audioReactiveHapticsEnabled'))))
        for row in (
            *self._audio_source_row(expander),
            b.switch('Keep Game Vibration', lambda s: dig(s, 'settings.audioReactiveHapticsMode') != 'replace',
                     lambda on: reactive('mode')('mix' if on else 'replace'),
                     subtitle='Off: only sound moves the motors'),
            b.scale('Strength', 0, 200, 10, lambda s: dig(s, 'settings.audioReactiveHapticsGainPercent'),
                    reactive('gainPercent')),
            b.combo('Bass Focus', BASS_FOCUS, lambda s: dig(s, 'settings.audioReactiveHapticsBassFocus'), reactive('bassFocus')),
            b.combo('Response', RESPONSE, lambda s: dig(s, 'settings.audioReactiveHapticsResponse'), reactive('response')),
            b.combo('Attack', ATTACK, lambda s: dig(s, 'settings.audioReactiveHapticsAttack'), reactive('attack')),
            b.combo('Release', RELEASE, lambda s: dig(s, 'settings.audioReactiveHapticsRelease'), reactive('release')),
        ):
            expander.add_row(row)

        return self._page(
            group('Haptic Feedback', None,
                  b.switch('Haptics', lambda s: dig(s, 'settings.hapticsEnabled'), self.setter('bridge:setHapticsEnabled')),
                  b.scale('Strength', 0, STANDARD_FEEDBACK_MAX, 20, lambda s: dig(s, 'settings.hapticsGainPercent'),
                          self.setter('bridge:setHapticsGain'), max_fn=feedback_max),
                  b.switch('Feedback Boost', lambda s: dig(s, 'settings.feedbackBoostEnabled'),
                           self.setter('bridge:setFeedbackBoostEnabled'), subtitle='Allow strength up to 500%'),
                  b.spin('Audio Buffer Length', 16, 128, 1, lambda s: dig(s, 'settings.hapticsBufferLength'),
                         self.setter('bridge:setHapticsBufferLength'),
                         subtitle='Lower is more responsive; below 64 may stutter'),
                  button_row('Test Haptics', 'Test', lambda: self.call('bridge:testHaptics'))),
            group('Classic Rumble', 'For games that use the older rumble motors',
                  b.switch('Classic Rumble', lambda s: dig(s, 'settings.classicRumbleEnabled'),
                           self.setter('bridge:setClassicRumbleEnabled')),
                  b.scale('Strength', 0, STANDARD_FEEDBACK_MAX, 20, lambda s: dig(s, 'settings.classicRumbleGainPercent'),
                          self.setter('bridge:setClassicRumbleGain'), max_fn=feedback_max),
                  b.switch('Compatibility Mode', lambda s: dig(s, 'settings.classicRumbleV1Enabled'),
                           self.setter('bridge:setClassicRumbleV1Enabled'), subtitle='Use the original rumble emulation'),
                  button_row('Test Rumble', 'Test', lambda: self.call('bridge:testClassicRumble'))),
            group(None, None, expander),
        )

    # ---- multi-step flows (calibration): a generator yields ('call', channel, *args) or ('sleep', ms)

    def run_flow(self, gen, on_error=None):
        def step(value=None, error=None):
            try:
                item = gen.throw(RuntimeError(error)) if error is not None else gen.send(value)
            except StopIteration:
                return
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                (on_error or self.toast)(str(exc))
                return
            if item[0] == 'sleep':
                GLib.timeout_add(item[1], lambda: (step(), GLib.SOURCE_REMOVE)[1])
            else:
                self.daemon.call(item[1], *item[2:], done=lambda v: step(v), fail=lambda m: step(error=m))
        step()

    # ---- triggers

    def _audio_source_row(self, expander):
        """Source picker: controller/system audio, a specific output (PipeWire sink) or one app."""
        b = self.b
        row = Adw.ComboRow(title='Source', enable_search=True, model=Gtk.StringList())
        state = {'options': [], 'devices': [], 'sessions': [], 'key': None}
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', valign=Gtk.Align.CENTER, css_classes=['flat'],
                             tooltip_text='Refresh Apps and Outputs')
        row.add_suffix(refresh)

        def rebuild():
            current = dig(self.snapshot, 'settings.audioReactiveHapticsSource', 'system-audio')
            options = [('controller-audio', 'controller-audio'), ('system-audio', 'system-audio'), ('mix', None)]
            options += [({'kind': 'output-device', 'deviceName': d['name'], 'displayName': d['description']}, None)
                        for d in state['devices'] if d['name'] != MIX_SINK_NAME]
            options += [(audio_source_from_session(x), None) for x in state['sessions']]
            keys = [audio_source_key(o) for o, _ in options]
            excluded_row.set_visible(audio_source_key(current) == 'mix')
            if audio_source_key(current) not in keys:
                options.append((current, None))  # keep the saved choice visible even if it is not running
                keys.append(audio_source_key(current))
            labels = [audio_source_label(o) for o, _ in options]
            signature = json.dumps([keys, labels, audio_source_key(current)])
            if signature == state['key']:
                return
            state['key'] = signature
            state['options'] = [o for o, _ in options]
            # Restore rather than clear: this also runs inside Binder.sync, and clearing the flag
            # there let every later syncer echo its value back to the daemon.
            was_syncing, b.syncing = b.syncing, True
            try:
                row.set_model(Gtk.StringList.new(labels))
                row.set_selected(keys.index(audio_source_key(current)))
            finally:
                b.syncing = was_syncing

        def fetch(*_):
            def devices(value):
                state['devices'] = value or []
                rebuild()

            def sessions(value):
                # Several streams of one app collapse into one choice.
                seen, unique = set(), []
                for x in value or []:
                    key = audio_source_key(audio_source_from_session(x))
                    if key not in seen:
                        seen.add(key)
                        unique.append(x)
                state['sessions'] = unique
                rebuild()
            self.call('bridge:listAudioHapticsOutputDevices', done=devices, quiet=True)
            self.call('bridge:listAudioHapticsSessions', done=sessions, quiet=True)

        def chosen(*_):
            index = row.get_selected()
            if b.syncing or index >= len(state['options']):
                return
            option = state['options'][index]
            if option == 'mix':
                self.call('daemon:setHapticsMix', True, done=lambda m: update_summary(m))
            else:
                self.call('bridge:setAudioReactiveHapticsConfig', {'source': option})
        row.connect('notify::selected', chosen)
        refresh.connect('clicked', fetch)
        expander.connect('notify::expanded', lambda e, _p: e.get_expanded() and fetch())
        def update_summary(mix):
            names = [a['name'] for a in (mix or {}).get('excluded', [])]
            excluded_row.set_subtitle('Nothing excluded' if not names else
                                      'Excluding ' + ', '.join(names[:4]) + (f' and {len(names) - 4} more'
                                                                             if len(names) > 4 else ''))
        excluded_row = Adw.ActionRow(title='Excluded Apps', activatable=True)
        excluded_row.add_suffix(Gtk.Image(icon_name='go-next-symbolic'))
        excluded_row.connect('activated', lambda *_: self._edit_exclusions(update_summary))
        excluded_row.set_visible(False)
        self.call('daemon:getHapticsMix', done=update_summary, quiet=True)
        b.syncers.append(lambda s: rebuild())
        return row, excluded_row

    def _edit_exclusions(self, on_saved):
        """Pick the apps whose sound must NOT drive haptics; every other app (games) feeds them."""
        def show(mix):
            excluded = {a['key']: a for a in mix.get('excluded', [])}
            apps = {s['key']: {'key': s['key'], 'name': s['name'], 'playing': True} for s in mix.get('streams', [])}
            for key, app in excluded.items():
                apps.setdefault(key, {'key': key, 'name': app['name'], 'playing': False})
            page = Adw.PreferencesPage()
            listing = Adw.PreferencesGroup(
                title='Don’t Use for Haptics',
                description='Checked apps never reach the controller. Every other app, like the game you are '
                            'playing, drives the haptics automatically.')
            checks = {}

            def add_row(app, checked):
                row = Adw.ActionRow(title=GLib.markup_escape_text(app['name']),
                                    subtitle='Playing now' if app.get('playing') else 'Not playing')
                check = Gtk.CheckButton(active=checked, valign=Gtk.Align.CENTER)
                row.add_prefix(check)
                row.set_activatable_widget(check)
                listing.add(row)
                checks[app['key']] = (check, app)
            for app in sorted(apps.values(), key=lambda a: (not a['playing'], a['name'].lower())):
                add_row(app, app['key'] in excluded)
            page.add(listing)
            entry = Adw.EntryRow(title='Add an App by Name', show_apply_button=True)

            def add_typed(*_):
                name = entry.get_text().strip()
                key = name.lower()
                if key and key not in checks:
                    add_row({'key': key, 'name': name, 'playing': False}, True)
                entry.set_text('')
            entry.connect('apply', add_typed)
            page.add(group(None, 'Use the program name, like “discord” or “firefox”.', entry))

            def save():
                chosen = [{'key': key, 'name': app['name']} for key, (check, app) in checks.items() if check.get_active()]
                self.call('daemon:setHapticsMix', True, chosen, done=on_saved)
            self._dialog('Excluded Apps', page, save)
        self.call('daemon:getHapticsMix', done=show)

    def _page_triggers(self):
        b = self.b
        lab = self.local.get('triggerLab', {})
        self.lab = {
            'linked': lab.get('linked', True),
            'drafts': lab.get('drafts') or {'l2': dict(TRIGGER_DEFAULT_EFFECT), 'r2': dict(TRIGGER_DEFAULT_EFFECT)},
            'profiles': lab.get('profiles', []),
        }
        editors = {
            'both': TriggerEditor(self, 'Both Triggers', 'l2', 'both'),
            'l2': TriggerEditor(self, 'Left Trigger (L2)', 'l2', 'l2'),
            'r2': TriggerEditor(self, 'Right Trigger (R2)', 'r2', 'r2'),
        }
        self.trigger_editors = editors
        linked = Adw.SwitchRow(title='Same Effect on Both Triggers', active=self.lab['linked'])

        def on_linked(*_):
            self.lab['linked'] = linked.get_active()
            if self.lab['linked']:
                self.lab['drafts']['r2'] = json.loads(json.dumps(self.lab['drafts']['l2']))
            self._save_lab()
            show()
        linked.connect('notify::active', on_linked)

        def show():
            editors['both'].group.set_visible(self.lab['linked'])
            editors['l2'].group.set_visible(not self.lab['linked'])
            editors['r2'].group.set_visible(not self.lab['linked'])
            for editor in editors.values():
                editor.load()
        show()

        power_cap = lambda s: POWER_SAVING_CAP if dig(s, 'settings.controllerPowerSavingEnabled') else 100  # noqa: E731
        return self._page(
            group('Adaptive Triggers', 'Resistance and vibration that games ask for',
                  b.switch('Adaptive Triggers', lambda s: dig(s, 'settings.adaptiveTriggersEnabled'),
                           self.setter('bridge:setAdaptiveTriggersEnabled')),
                  b.scale('Intensity', 0, 100, 10, lambda s: dig(s, 'settings.triggerEffectIntensityPercent'),
                          self.setter('bridge:setTriggerEffectIntensity'), max_fn=power_cap),
                  b.combo('Test Effect', TRIGGER_TESTS, lambda s: dig(s, 'settings.triggerTestMode'),
                          self.setter('bridge:setTriggerTestMode')),
                  button_row('Test Triggers', 'Test', lambda: self.call(
                      'bridge:testAdaptiveTriggers', dig(self.snapshot, 'settings.triggerTestMode', 'feedback'), 'both')),
                  button_row('Reset Triggers', 'Reset', lambda: self.call('bridge:resetAdaptiveTriggers'),
                             subtitle='Clear any effect a game or the Trigger Lab left applied')),
            group('Trigger Lab', 'Compose an effect and send it straight to the controller. It stays until a '
                                 'game sets its own or you reset the triggers.', linked),
            editors['both'].group, editors['l2'].group, editors['r2'].group,
        )

    def _save_lab(self):
        self.local.set('triggerLab', self.lab)

    def _send_trigger(self, side, effect):
        off = {'type': 'off'}
        if side == 'both':
            self.call('bridge:setRawTriggerEffect', 'both', effect, effect)
        elif side == 'l2':
            self.call('bridge:setRawTriggerEffect', 'l2', off, effect)
        else:
            self.call('bridge:setRawTriggerEffect', 'r2', effect, off)

    # ---- sticks

    def _page_sticks(self):
        b = self.b
        self.calibration = {'busy': False, 'hold': 0}

        def deadzone(side):
            def send(value):
                left = dig(self.snapshot, 'settings.stickDeadzoneLeftPercent', 0)
                right = dig(self.snapshot, 'settings.stickDeadzoneRightPercent', 0)
                self.call('bridge:setStickDeadzone', value if side == 'left' else left,
                          value if side == 'right' else right)
            return send

        self.cal_status = Adw.ActionRow(title='Last Result', subtitle='No calibration run yet', css_classes=['property'])
        centre = button_row('Centre', 'Calibrate', lambda: self._calibrate(CAL_CENTRE),
                            subtitle='Fixes drift. Leave both sticks untouched while it runs.')
        sweep = button_row('Range', 'Calibrate', lambda: self._calibrate(CAL_RANGE),
                           subtitle='Fixes sticks that do not reach the edge. You sweep both sticks around the rim.')
        perm_centre = button_row('Write Centre Permanently', 'Write…', lambda: self._confirm_permanent(CAL_CENTRE),
                                 style='destructive-action')
        perm_range = button_row('Write Range Permanently', 'Write…', lambda: self._confirm_permanent(CAL_RANGE),
                                style='destructive-action')
        cal_rows = [centre, sweep, perm_centre, perm_range]
        b.syncers.append(lambda s: [r.set_sensitive(bool(dig(s, 'status.controllerConnected'))
                                                    and not self.calibration['busy']) for r in cal_rows])
        self.cal_rows = cal_rows

        return self._page(
            group('Deadzone', 'Radial deadzone as a share of stick travel. 0 turns it off.',
                  b.spin('Left Stick', 0, 50, 1, lambda s: dig(s, 'settings.stickDeadzoneLeftPercent'), deadzone('left')),
                  b.spin('Right Stick', 0, 50, 1, lambda s: dig(s, 'settings.stickDeadzoneRightPercent'), deadzone('right'))),
            group('Calibration', 'Temporary: restarting the controller brings back its previous calibration. '
                                 'Input is held from games while it runs.', centre, sweep, self.cal_status),
            group('Permanent Calibration',
                  'Writes the calibration into the controller’s permanent storage. A reset will not undo it, and an '
                  'interrupted write can leave the controller unusable. Run the temporary calibration first.',
                  perm_centre, perm_range),
            group(None, None, button_row('Input Tester', 'Open', self.open_tester,
                                         subtitle='Watch every button, stick, trigger and sensor live')),
        )

    def _set_cal_busy(self, busy):
        self.calibration['busy'] = busy
        connected = bool(dig(self.snapshot, 'status.controllerConnected'))
        for row in self.cal_rows:
            row.set_sensitive(connected and not busy)

    def _hold_input(self, on):
        """Keep the controller's input away from games while calibrating (upstream tester lease)."""
        if self.calibration['hold']:
            GLib.source_remove(self.calibration['hold'])
            self.calibration['hold'] = 0
        if on:
            renew = lambda: (self.call('bridge:holdInputForwarding', INPUT_HOLD_MS, quiet=True), True)[1]  # noqa: E731
            renew()
            self.calibration['hold'] = GLib.timeout_add(INPUT_HOLD_RENEW_MS, renew)
        else:
            self.call('bridge:holdInputForwarding', 0, quiet=True)

    def _cal_step(self, op, target, expected):
        yield ('call', 'bridge:sendStickCalibration', op, target)
        yield ('sleep', 250)  # the reply crosses Bluetooth asynchronously
        status = yield ('call', 'bridge:readCalibrationStatus')
        if status and status.get('received'):
            self.cal_status.set_subtitle(f'Controller replied: target {status["target"]}, code {status["code"]}')
        return calibration_step_accepted(status, target, expected)

    def _calibrate(self, target, permanent=False):
        if self.calibration['busy']:
            return
        label = 'Centre' if target == CAL_CENTRE else 'Range'
        self._set_cal_busy(True)
        self._hold_input(True)
        state = {'awaiting_sweep': False}

        def flow():
            try:
                if permanent:
                    yield ('call', 'bridge:setNvsUnlocked', True)
                # No cancel opcode exists: a session left open by an interrupted run blocks every
                # begin until committed, so retry once behind a store (upstream beginCalibration).
                ok = yield from self._cal_step(CAL_OP_BEGIN, target, CAL_OPEN)
                if not ok:
                    yield from self._cal_step(CAL_OP_STORE, target, CAL_COMMITTED)
                    ok = yield from self._cal_step(CAL_OP_BEGIN, target, CAL_OPEN)
                    self.toast('A previous calibration session was still open and had to be closed; '
                               'that close may already have changed the calibration')
                if not ok:
                    self.cal_status.set_subtitle('Could not start calibration. Restart the controller and try again.')
                    return
                if target == CAL_CENTRE:
                    self.cal_status.set_subtitle('Sampling centre — leave the sticks alone')
                    yield ('sleep', 600)
                    if not (yield from self._cal_step(CAL_OP_SAMPLE, target, CAL_OPEN)):
                        self.cal_status.set_subtitle('Sampling was refused. Nothing was stored.')
                        return
                    self.cal_status.set_subtitle('Storing…')
                    if (yield from self._cal_step(CAL_OP_STORE, target, CAL_COMMITTED)):
                        self.cal_status.set_subtitle(f'{label} calibrated' + (' permanently' if permanent else ''))
                        self.toast(f'{label} calibrated')
                    else:
                        self.cal_status.set_subtitle('The controller did not confirm the write.')
                else:
                    state['awaiting_sweep'] = True
            finally:
                if permanent:
                    # Re-lock even after a failure: leaving NVS writable is the dangerous outcome.
                    yield ('call', 'bridge:setNvsUnlocked', False)
                if state['awaiting_sweep']:
                    GLib.idle_add(lambda: (self._sweep_dialog(permanent), GLib.SOURCE_REMOVE)[1])
                else:
                    self._hold_input(False)
                    self._set_cal_busy(False)

        def failed(message):
            self.cal_status.set_subtitle(message)
            self.toast(message)
            self._hold_input(False)
            self._set_cal_busy(False)
        self.run_flow(flow(), on_error=failed)

    def _sweep_dialog(self, permanent):
        sweeps = {'left': Sweep(), 'right': Sweep()}
        poll = {'id': 0, 'busy': False, 'done': False}
        dialog = Adw.Dialog(title='Range Calibration', content_width=520, can_close=False)
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label='Cancel')
        finish = Gtk.Button(label='Finish', css_classes=['suggested-action'], sensitive=False)
        header.pack_start(cancel)
        header.pack_end(finish)
        intro = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, label=(
            'Push each stick to its limit and sweep slowly around the rim: one full circle clockwise, then one '
            'counterclockwise, about two seconds per circle. A gap is a direction the controller has not seen yet.'))
        areas = Gtk.Box(spacing=24, halign=Gtk.Align.CENTER)
        labels = {}
        drawings = {}
        for side, title in (('left', 'Left Stick'), ('right', 'Right Stick')):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            area = Gtk.DrawingArea(content_width=180, content_height=180)
            area.set_draw_func(lambda a, cr, w, h, sw=sweeps[side]: draw_sweep(a, cr, w, h, sw))
            caption = Gtk.Label(label=title, css_classes=['heading'])
            info = Gtk.Label(css_classes=['dim-label', 'numeric', 'caption'])
            for w in (area, caption, info):
                column.append(w)
            areas.append(column)
            labels[side], drawings[side] = info, area
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=12, margin_bottom=24,
                       margin_start=24, margin_end=24)
        body.append(intro)
        body.append(areas)
        view = Adw.ToolbarView(content=body)
        view.add_top_bar(header)
        dialog.set_child(view)

        def tick():
            if poll['done']:
                return GLib.SOURCE_REMOVE
            if not poll['busy']:
                poll['busy'] = True

                def got(snapshot):
                    poll['busy'] = False
                    # ControllerInputSnapshot: {controllerConnected, raw, state: DualSenseInputState | null}
                    state = (snapshot or {}).get('state')
                    if not state:
                        return
                    now = GLib.get_monotonic_time() / 1000
                    sweeps['left'].record(state['leftStickX'], state['leftStickY'], now)
                    sweeps['right'].record(state['rightStickX'], state['rightStickY'], now)
                    for side, sw in sweeps.items():
                        labels[side].set_label(f'CW {sw.coverage("cw"):.0%} · CCW {sw.coverage("ccw"):.0%}')
                        drawings[side].queue_draw()
                    finish.set_sensitive(all(sw.complete for sw in sweeps.values()))
                self.daemon.call('bridge:readControllerInput', done=got, quiet=True,
                                 fail=lambda _m: poll.__setitem__('busy', False))
            return GLib.SOURCE_CONTINUE
        poll['id'] = GLib.timeout_add(40, tick)

        def close(stored_flow=None):
            poll['done'] = True
            dialog.force_close()
            if stored_flow is None:
                self.cal_status.set_subtitle('Range calibration cancelled. Nothing was stored.')
                self._hold_input(False)
                self._set_cal_busy(False)

        def store():
            close(stored_flow=True)

            def flow():
                try:
                    if permanent:
                        yield ('call', 'bridge:setNvsUnlocked', True)
                    self.cal_status.set_subtitle('Storing…')
                    if (yield from self._cal_step(CAL_OP_STORE, CAL_RANGE, CAL_COMMITTED)):
                        self.cal_status.set_subtitle('Range calibrated' + (' permanently' if permanent else ''))
                        self.toast('Range calibrated')
                    else:
                        self.cal_status.set_subtitle('The controller did not confirm the write.')
                finally:
                    if permanent:
                        yield ('call', 'bridge:setNvsUnlocked', False)
                    self._hold_input(False)
                    self._set_cal_busy(False)
            self.run_flow(flow())
        cancel.connect('clicked', lambda *_: close())
        finish.connect('clicked', lambda *_: store())
        self._sweep_finish = finish  # dev snapshots press it
        dialog.present(self)

    def _confirm_permanent(self, target):
        what = 'centre' if target == CAL_CENTRE else 'range'
        dialog = Adw.AlertDialog(heading='Write Calibration Permanently?', body_use_markup=True, body=(
            f'This unlocks the controller’s permanent storage and writes the {what} calibration into it. '
            '<b>A reset will not undo it.</b>\n\n'
            '• <b>It can permanently break the controller.</b> Be prepared to lose it.\n'
            '• <b>Nobody can guarantee it works.</b> The unlock sequence is reverse-engineered and was worked '
            'out on a handful of units.\n'
            '• <b>There is no undo.</b> Reverting means calibrating again and getting a good result.\n'
            '• <b>An interruption is the dangerous case.</b> A disconnect or a dead battery mid-write can leave '
            'calibration data that is neither the old values nor the new ones.\n\n'
            f'Type <b>{CAL_CONFIRM_PHRASE}</b> to continue.'))
        entry = Gtk.Entry(placeholder_text=CAL_CONFIRM_PHRASE)
        dialog.set_extra_child(entry)
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('write', 'Write Permanently')
        dialog.set_response_appearance('write', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_enabled('write', False)
        dialog.set_default_response('cancel')
        entry.connect('changed', lambda e: dialog.set_response_enabled(
            'write', e.get_text().strip().upper() == CAL_CONFIRM_PHRASE))
        dialog.connect('response', lambda _d, r: r == 'write' and self._calibrate(target, permanent=True))
        dialog.present(self)

    def _page_lighting(self):
        b = self.b
        color_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        color_row = Adw.ActionRow(title='Color')
        color_row.add_suffix(color_button)
        color_row.set_activatable_widget(color_button)

        def color_changed(*_):
            if b.syncing:
                return
            b._user_touch(color_button)
            rgba = color_button.get_rgba()
            hexcolor = '#{:02x}{:02x}{:02x}'.format(*(round(c * 255) for c in (rgba.red, rgba.green, rgba.blue)))
            self.call('bridge:setLightbarColor', hexcolor, dig(self.snapshot, 'settings.lightbarBrightnessPercent', 100))
        color_button.connect('notify::rgba', color_changed)

        def color_sync(s):
            value = dig(s, 'settings.lightbarColor')
            rgba = Gdk.RGBA()
            if value and rgba.parse(value) and not b._held(color_button):
                color_button.set_rgba(rgba)
        b.syncers.append(color_sync)

        power_cap = lambda s: POWER_SAVING_CAP if dig(s, 'settings.controllerPowerSavingEnabled') else 100  # noqa: E731
        return self._page(
            group('Light Bar', None,
                  b.switch('Light Bar', lambda s: dig(s, 'settings.lightbarEnabled'), self.setter('bridge:setLightbarEnabled')),
                  b.switch('Override Game Colors', lambda s: dig(s, 'settings.lightbarOverrideEnabled'),
                           self.setter('bridge:setLightbarOverrideEnabled'),
                           subtitle='Always use this color, even when a game sets one'),
                  color_row,
                  b.scale('Brightness', 0, 100, 10, lambda s: dig(s, 'settings.lightbarBrightnessPercent'),
                          lambda v: self.call('bridge:setLightbarColor',
                                              dig(self.snapshot, 'settings.lightbarColor', '#0000ff'), v),
                          max_fn=power_cap)),
            group('Indicators', None,
                  b.switch('Mute Button Light', lambda s: dig(s, 'settings.ledEnabled'), self.setter('bridge:setLedEnabled')),
                  b.switch('Player Lights', lambda s: dig(s, 'settings.playerLedEnabled'),
                           self.setter('bridge:setPlayerLedEnabled'))),
        )

    # ---- input: buttons, remapping, chords

    def _is_edge(self, s):
        """Show Edge-only controls for a connected Edge, else the last controller seen (like upstream)."""
        status = s.get('status') or {}
        if status.get('controllerConnected') and status.get('controllerType') not in (None, 'unknown'):
            return status['controllerType'] == 'dualsense-edge'
        history = dig(s, 'settings.controllerHistory', []) or []
        if history:
            return max(history, key=lambda e: e.get('lastSeenAt', 0)).get('controllerType') == 'dualsense-edge'
        return False

    def _mute_chord_starter_active(self, s):
        st = s.get('settings', {})
        return st.get('muteButtonMode') == 'chord' or (
            st.get('muteButtonMode') == 'keyboard' and st.get('muteKeyboardChordStarterEnabled'))

    def _send_mute(self, **changes):
        st = self.snapshot['settings']
        value = {
            'mode': st['muteButtonMode'], 'usage': st['muteKeyboardUsage'], 'modifiers': st['muteKeyboardModifiers'],
            'behavior': st['muteKeyboardBehavior'], 'starter': st['muteKeyboardChordStarterEnabled'], **changes}
        self.call('bridge:setMuteButtonAction', value['mode'], value['usage'], value['modifiers'],
                  value['behavior'], value['starter'])

    def _page_buttons(self):
        b = self.b
        keyboard = lambda s: dig(s, 'settings.muteButtonMode') == 'keyboard'  # noqa: E731

        key_row = b.combo('Key', [(usage, label) for label, usage in MUTE_KEYS],
                          lambda s: dig(s, 'settings.muteKeyboardUsage'), lambda usage: self._send_mute(usage=usage))
        key_row.set_enable_search(True)

        modifiers_row = Adw.ActionRow(title='Modifiers')
        box = Gtk.Box(css_classes=['linked'], valign=Gtk.Align.CENTER)
        toggles = []
        for label, bit in MUTE_MODIFIERS:
            toggle = Gtk.ToggleButton(label=label)
            toggle._bit = bit

            def flipped(button):
                if b.syncing:
                    return
                b._user_touch(box)
                mask = sum(t._bit for t in toggles if t.get_active())
                self._send_mute(modifiers=mask)
            toggle.connect('toggled', flipped)
            toggles.append(toggle)
            box.append(toggle)
        modifiers_row.add_suffix(box)

        def modifiers_sync(s):
            if b._held(box):
                return
            mask = dig(s, 'settings.muteKeyboardModifiers', 0) or 0
            for t in toggles:
                t.set_active(bool(mask & t._bit))
        b.syncers.append(modifiers_sync)

        keyboard_rows = [
            key_row, modifiers_row,
            b.combo('Behavior', MUTE_BEHAVIORS, lambda s: dig(s, 'settings.muteKeyboardBehavior'),
                    lambda v: self._send_mute(behavior=v)),
            b.switch('Also Starts Chords', lambda s: dig(s, 'settings.muteKeyboardChordStarterEnabled'),
                     lambda v: self._send_mute(starter=v), subtitle='Hold Mute and press a button to run a chord'),
        ]
        for row in keyboard_rows:
            b.visible_when(row, keyboard)

        return self._page(
            group('Mute Button', None,
                  b.combo('Action', MUTE_MODES, lambda s: dig(s, 'settings.muteButtonMode'),
                          lambda mode: self._send_mute(mode=mode)),
                  *keyboard_rows),
            group('Shortcuts', None,
                  b.switch('Sleep Shortcut', lambda s: dig(s, 'settings.sleepKeybindEnabled'),
                           self.setter('bridge:setSleepKeybindEnabled'),
                           subtitle='PS + Triangle turns the controller off'),
                  b.switch('Speaker Volume Shortcut', lambda s: dig(s, 'settings.speakerVolumeShortcutEnabled'),
                           self.setter('bridge:setSpeakerVolumeShortcutEnabled'),
                           subtitle='PS + D-pad Up/Down changes the speaker volume')),
            group('Touchpad', None,
                  b.switch('Use Touchpad as Mouse', lambda s: dig(s, 'settings.touchpadMouseEnabled'),
                           self.setter('bridge:setTouchpadMouseEnabled'))),
        )

    def _page_remapping(self):
        b = self.b
        profile = self._profile_row(
            'Remapping Profile', 'Button layouts follow the controller too', 'buttonRemappingProfiles',
            'selectedButtonRemappingProfileId', prefix='remap', select='bridge:selectButtonRemappingProfile',
            save='bridge:saveButtonRemappingProfile', update='bridge:updateButtonRemappingProfile',
            rename='bridge:renameButtonRemappingProfile', delete='bridge:deleteButtonRemappingProfile',
            reset='bridge:restoreButtonRemappingDefaults')
        summary = Adw.PreferencesGroup()

        def summary_sync(s):
            draft = dig(s, 'settings.buttonRemappingDraft', {}) or {}
            changed = sum(1 for k, v in draft.items() if k != v)
            summary.set_description('No buttons remapped' if not changed else
                                    f'{changed} button{"s" if changed != 1 else ""} remapped')
        b.syncers.append(summary_sync)
        summary.add(profile)

        def button_rows(ids):
            rows = []
            for button in ids:
                targets = REMAP_TARGETS + ([button] if button in REMAP_EDGE else [])
                labels = [REMAP_LABELS[t] for t in targets]
                row = b.combo(REMAP_LABELS[button], list(zip(targets, labels)),
                              lambda s, k=button: dig(s, f'settings.buttonRemappingDraft.{k}'),
                              lambda target, k=button: self.call('bridge:setButtonRemap', k, target))
                row.add_prefix(glyph_widget(button))

                def mark(s, row=row, k=button):
                    target = dig(s, f'settings.buttonRemappingDraft.{k}')
                    remapped = target not in (None, k)
                    row.set_subtitle(f'Acts as {REMAP_LABELS.get(target, target)}' if remapped else '')
                    (row.add_css_class if remapped else row.remove_css_class)('ds5-remapped')
                b.syncers.append(mark)
                rows.append(row)
            return rows

        edge = group('DualSense Edge', 'Back buttons and function buttons', *button_rows(REMAP_EDGE))
        b.visible_when(edge, lambda s: self._is_edge(s) or any(
            dig(s, f'settings.buttonRemappingDraft.{k}') not in (None, k) for k in REMAP_EDGE))
        return self._page(
            summary,
            group('Left Side', None, *button_rows(REMAP_LEFT)),
            group('Right Side', None, *button_rows(REMAP_RIGHT)),
            edge,
        )

    # chords

    def _chord_state(self):
        st = self.snapshot['settings']
        return [dict(f) for f in st.get('chordFunctions', [])], [dict(a) for a in st.get('chordAssignments', [])]

    def _save_chords(self, functions, assignments):
        self.call('bridge:setChordConfiguration', functions, assignments)

    def _chord_starters(self, s, keep=None):
        edge = self._is_edge(s)
        mute = self._mute_chord_starter_active(s)
        return [(k, label) for k, label in CHORD_STARTERS
                if k == 'ps' or (k in ('lfn', 'rfn') and edge) or (k == 'mute' and mute) or k == keep]

    def _chord_buttons(self, s, starter):
        ids = REMAP_STANDARD_TARGETS + (['lb', 'rb'] if self._is_edge(s) else [])
        return [(k, REMAP_LABELS[k]) for k in ids if starter == 'ps' or k not in CHORD_EDGE_RESERVED]

    def _chord_conflict(self, s, assignment, assignments):
        st = s['settings']
        key = (assignment['starter'], assignment['button'])
        if sum(1 for a in assignments if (a['starter'], a['button']) == key) > 1:
            return 'Assigned more than once'
        if st.get('sleepKeybindEnabled') and key == ('ps', 'triangle'):
            return 'Taken by the Sleep Shortcut'
        if st.get('speakerVolumeShortcutEnabled') and key in (('ps', 'dpad-up'), ('ps', 'dpad-down')):
            return 'Taken by the Speaker Volume Shortcut'
        if assignment['starter'] == 'mute' and not self._mute_chord_starter_active(s):
            return 'Mute button is not set to start chords'
        return None

    def _page_chords(self):
        b = self.b
        functions_group = Adw.PreferencesGroup(
            title='Functions', description='What a chord can do: press keys, control media or change a setting.')
        add_function = Gtk.Button(icon_name='list-add-symbolic', css_classes=['flat'], tooltip_text='Add Function')
        add_function.connect('clicked', lambda *_: self._edit_chord_function(None))
        functions_group.set_header_suffix(add_function)

        chords_group = Adw.PreferencesGroup(
            title='Chords', description='Hold a starter button, then press another button.')
        add_chord = Gtk.Button(icon_name='list-add-symbolic', css_classes=['flat'], tooltip_text='Add Chord')
        add_chord.connect('clicked', lambda *_: self._edit_chord_assignment(None))
        chords_group.set_header_suffix(add_chord)

        rows = {'functions': [], 'chords': []}
        last = {'key': None}

        def rebuild(s):
            st = s['settings']
            key = json.dumps([st.get('chordFunctions'), st.get('chordAssignments'), self._is_edge(s),
                              self._mute_chord_starter_active(s), st.get('sleepKeybindEnabled'),
                              st.get('speakerVolumeShortcutEnabled')])
            if key == last['key']:
                return
            last['key'] = key
            for name, grp in (('functions', functions_group), ('chords', chords_group)):
                for row in rows[name]:
                    grp.remove(row)
                rows[name].clear()
            functions = st.get('chordFunctions', [])
            assignments = st.get('chordAssignments', [])
            add_chord.set_sensitive(bool(functions) and len(assignments) < MAX_CHORD_ASSIGNMENTS)

            if not functions:
                row = Adw.ActionRow(title='No functions yet', subtitle='Add one to start making chords')
                functions_group.add(row)
                rows['functions'].append(row)
            for func in functions:
                row = Adw.ActionRow(title=GLib.markup_escape_text(func['name']),
                                    subtitle=GLib.markup_escape_text(chord_function_summary(func)), activatable=True)
                row.add_prefix(Gtk.Image(icon_name={'keyboard': 'input-keyboard-symbolic',
                                                    'media': 'media-playback-start-symbolic'}.get(
                    func['type'], 'emblem-system-symbolic')))
                row.add_suffix(Gtk.Image(icon_name='go-next-symbolic'))
                row.connect('activated', lambda _r, f=func: self._edit_chord_function(f))
                functions_group.add(row)
                rows['functions'].append(row)

            names = {f['id']: f['name'] for f in functions}
            if not assignments:
                row = Adw.ActionRow(title='No chords yet')
                chords_group.add(row)
                rows['chords'].append(row)
            for assignment in assignments:
                conflict = self._chord_conflict(s, assignment, assignments)
                title = f'{label_of(CHORD_STARTERS, assignment["starter"])} + {REMAP_LABELS.get(assignment["button"])}'
                row = Adw.ActionRow(title=title, activatable=True,
                                    subtitle=GLib.markup_escape_text(conflict or names.get(assignment['functionId'],
                                                                                           'Missing function')))
                if conflict:
                    row.add_css_class('error')
                    row.add_prefix(Gtk.Image(icon_name='dialog-warning-symbolic'))
                else:
                    row.add_prefix(glyph_widget(assignment['button'], 24))
                remove = Gtk.Button(icon_name='user-trash-symbolic', valign=Gtk.Align.CENTER, css_classes=['flat'],
                                    tooltip_text='Remove Chord')
                remove.connect('clicked', lambda _b, a=assignment: self._save_chords(
                    self._chord_state()[0], [x for x in self._chord_state()[1] if x['id'] != a['id']]))
                row.add_suffix(remove)
                row.connect('activated', lambda _r, a=assignment: self._edit_chord_assignment(a))
                chords_group.add(row)
                rows['chords'].append(row)
        b.syncers.append(rebuild)
        return self._page(chords_group, functions_group)

    def _dialog(self, title, content, on_save, save_label='Save', on_delete=None):
        dialog = Adw.Dialog(title=title, content_width=440)
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label='Cancel')
        cancel.connect('clicked', lambda *_: dialog.close())
        save = Gtk.Button(label=save_label, css_classes=['suggested-action'])
        save.connect('clicked', lambda *_: on_save() is not False and dialog.close())
        self._last_dialog_save = save  # dev snapshots press it
        header.pack_start(cancel)
        header.pack_end(save)
        view = Adw.ToolbarView(content=content)
        view.add_top_bar(header)
        if on_delete:
            delete = Gtk.Button(label='Delete', css_classes=['destructive-action'], halign=Gtk.Align.CENTER,
                                margin_bottom=18)
            delete.connect('clicked', lambda *_: (dialog.close(), on_delete()))
            view.add_bottom_bar(delete)
        dialog.set_child(view)
        dialog.present(self)
        return dialog

    def _edit_chord_function(self, func):
        func = dict(func or {'type': 'keyboard', 'keys': ['Ctrl', 'Shift', 'Esc'], 'name': ''})
        page = Adw.PreferencesPage()
        name = Adw.EntryRow(title='Name', text=func.get('name', ''))
        name.connect('changed', lambda *_: name.get_text() and len(name.get_text()) > MAX_CHORD_FUNCTION_NAME
                     and name.set_text(name.get_text()[:MAX_CHORD_FUNCTION_NAME]))
        kind = Adw.ComboRow(title='Type', model=Gtk.StringList.new([l for _, l in CHORD_FUNCTION_TYPES]))
        kind.set_selected([k for k, _ in CHORD_FUNCTION_TYPES].index(func['type']))
        page.add(group(None, None, name, kind))

        keys = func.get('keys', []) if func['type'] == 'keyboard' else ['Ctrl', 'Shift', 'Esc']
        key_values = [v for _, v in CHORD_KEYS]
        main_key = next((k for k in keys if k in key_values), 'Esc')
        key_row = Adw.ComboRow(title='Key', enable_search=True, model=Gtk.StringList.new([l for l, _ in CHORD_KEYS]))
        key_row.set_selected(key_values.index(main_key))
        mods_row = Adw.ActionRow(title='Modifiers', subtitle=f'Up to {MAX_KEYBOARD_FUNCTION_KEYS - 1}')
        mods_box = Gtk.Box(css_classes=['linked'], valign=Gtk.Align.CENTER)
        mod_toggles = []
        for label, value in CHORD_MODIFIERS:
            toggle = Gtk.ToggleButton(label=label, active=value in keys)
            toggle._value = value
            mod_toggles.append(toggle)
            mods_box.append(toggle)

        def limit_mods(*_):
            on = [t for t in mod_toggles if t.get_active()]
            for t in mod_toggles:
                t.set_sensitive(t.get_active() or len(on) < MAX_KEYBOARD_FUNCTION_KEYS - 1)
        for t in mod_toggles:
            t.connect('toggled', limit_mods)
        limit_mods()
        mods_row.add_suffix(mods_box)
        keyboard_group = group('Keyboard Shortcut', None, mods_row, key_row)

        media_row = Adw.ComboRow(title='Action', model=Gtk.StringList.new([l for _, l in CHORD_MEDIA]))
        media_ids = [k for k, _ in CHORD_MEDIA]
        media_row.set_selected(media_ids.index(func['action']) if func['type'] == 'media' else 0)
        media_group = group('Media', None, media_row)

        setting_ids = [k for k, _ in CHORD_SETTINGS]
        setting_row = Adw.ComboRow(title='Action', model=Gtk.StringList.new([l for _, l in CHORD_SETTINGS]))
        setting_row.set_selected(setting_ids.index(func['action'])
                                 if func['type'] == 'controller-setting' else setting_ids.index('sleep-controller'))
        step_row = Adw.SpinRow.new_with_range(1, 100, 1)
        step_row.set_title('Step')
        step_row.set_subtitle('How much each press changes the setting, in percent')
        step_row.set_value(func.get('stepPercent') or default_step(setting_ids[setting_row.get_selected()]))
        setting_group = group('Controller Setting', None, setting_row, step_row)

        def on_setting(*_):
            action = setting_ids[setting_row.get_selected()]
            step_row.set_visible(step_action(action))
        setting_row.connect('notify::selected', on_setting)
        on_setting()
        for g in (keyboard_group, media_group, setting_group):
            page.add(g)

        def on_kind(*_):
            current = CHORD_FUNCTION_TYPES[kind.get_selected()][0]
            keyboard_group.set_visible(current == 'keyboard')
            media_group.set_visible(current == 'media')
            setting_group.set_visible(current == 'controller-setting')
        kind.connect('notify::selected', on_kind)
        on_kind()

        def save():
            current = CHORD_FUNCTION_TYPES[kind.get_selected()][0]
            result = {'id': func.get('id') or new_id('function'), 'type': current}
            if current == 'keyboard':
                result['keys'] = ([t._value for t in mod_toggles if t.get_active()]
                                  + [key_values[key_row.get_selected()]])[:MAX_KEYBOARD_FUNCTION_KEYS]
            elif current == 'media':
                result['action'] = media_ids[media_row.get_selected()]
            else:
                action = setting_ids[setting_row.get_selected()]
                result['action'] = action
                result['stepPercent'] = int(step_row.get_value()) if step_action(action) else default_step(action)
            default_name = {'keyboard': 'Shortcut', 'media': 'Media', 'controller-setting': 'Setting'}[current]
            result['name'] = (name.get_text().strip() or default_name)[:MAX_CHORD_FUNCTION_NAME]
            functions, assignments = self._chord_state()
            if func.get('id'):
                functions = [result if f['id'] == func['id'] else f for f in functions]
            else:
                functions.append(result)
            self._save_chords(functions, assignments)

        def delete():
            used = [a for a in self._chord_state()[1] if a['functionId'] == func['id']]
            body = f'It is used by {len(used)} chord{"s" if len(used) != 1 else ""}, which will be removed too.' \
                if used else 'This function will be removed.'

            def go():
                functions, assignments = self._chord_state()
                self._save_chords([f for f in functions if f['id'] != func['id']],
                                  [a for a in assignments if a['functionId'] != func['id']])
            self._confirm(f'Delete “{func["name"]}”?', body, 'Delete', go)

        self._dialog('Edit Function' if func.get('id') else 'New Function', page, save,
                     on_delete=delete if func.get('id') else None)

    def _edit_chord_assignment(self, assignment):
        s = self.snapshot
        functions, _ = self._chord_state()
        if not functions:
            self.toast('Add a function first')
            return
        assignment = dict(assignment or {'starter': 'ps', 'button': None,
                                         'functionId': functions[0]['id']})
        starters = self._chord_starters(s, keep=assignment['starter'])
        starter_ids = [k for k, _ in starters]
        starter_row = Adw.ComboRow(title='Hold', model=Gtk.StringList.new([l for _, l in starters]))
        starter_row.set_selected(starter_ids.index(assignment['starter']) if assignment['starter'] in starter_ids else 0)
        button_row_ = Adw.ComboRow(title='Then Press')
        button_ids = []

        def fill_buttons(*_):
            starter = starter_ids[starter_row.get_selected()]
            options = self._chord_buttons(s, starter)
            previous = button_ids[button_row_.get_selected()] if button_ids and button_row_.get_selected() < len(
                button_ids) else assignment.get('button')
            button_ids[:] = [k for k, _ in options]
            button_row_.set_model(Gtk.StringList.new([l for _, l in options]))
            if previous not in button_ids:
                # New chord: first button that is free and not taken by a built-in shortcut.
                taken = {(a['starter'], a['button']) for a in self._chord_state()[1]}
                previous = next((k for k in button_ids if (starter, k) not in taken and not self._chord_conflict(
                    s, {'starter': starter, 'button': k}, [])), button_ids[0] if button_ids else None)
            if previous in button_ids:
                button_row_.set_selected(button_ids.index(previous))
        starter_row.connect('notify::selected', fill_buttons)
        fill_buttons()

        function_ids = [f['id'] for f in functions]
        function_row = Adw.ComboRow(title='Run', model=Gtk.StringList.new([f['name'] for f in functions]))
        if assignment['functionId'] in function_ids:
            function_row.set_selected(function_ids.index(assignment['functionId']))
        page = Adw.PreferencesPage()
        page.add(group(None, None, starter_row, button_row_, function_row))

        def save():
            starter = starter_ids[starter_row.get_selected()]
            button = button_ids[button_row_.get_selected()]
            fns, assignments = self._chord_state()
            clash = next((a for a in assignments if (a['starter'], a['button']) == (starter, button)
                          and a['id'] != assignment.get('id')), None)
            result = {'id': assignment.get('id') or new_id(f'chord-{starter}-{button}'), 'kind': 'chord',
                      'starter': starter, 'button': button, 'functionId': function_ids[function_row.get_selected()]}
            assignments = [a for a in assignments if a is not clash and a['id'] != result['id']] + [result] \
                if not assignment.get('id') else [result if a['id'] == result['id'] else a
                                                  for a in assignments if a is not clash]
            if clash:
                self.toast('Replaced the chord that used the same buttons')
            self._save_chords(fns, assignments)

        self._dialog('Edit Chord' if assignment.get('id') else 'New Chord', page, save,
                     on_delete=(lambda: self._save_chords(self._chord_state()[0], [
                         a for a in self._chord_state()[1] if a['id'] != assignment['id']]))
                     if assignment.get('id') else None)


    def _page_system(self):
        b = self.b
        idle = Adw.ExpanderRow(title='Turn Off When Idle', show_enable_switch=True,
                               subtitle='Turn the controller off after a period without input')

        def idle_changed(*_):
            if not b.syncing:
                b._user_touch(idle)
                self.call('bridge:setIdleDisconnectEnabled', idle.get_enable_expansion())
        idle.connect('notify::enable-expansion', idle_changed)
        b.syncers.append(lambda s: None if b._held(idle) else idle.set_enable_expansion(
            bool(dig(s, 'settings.idleDisconnectEnabled'))))
        idle.add_row(b.spin('After (minutes)', 1, 120, 1, lambda s: dig(s, 'settings.idleDisconnectTimeoutMinutes'),
                            self.setter('bridge:setIdleDisconnectTimeoutMinutes')))

        return self._page(
            group('Connection', None,
                  b.combo('Polling Rate', POLLING, lambda s: dig(s, 'settings.pollingRateMode'),
                          self.setter('bridge:setPollingRateMode')),
                  b.switch('Power Saving', lambda s: dig(s, 'settings.controllerPowerSavingEnabled'),
                           self.setter('bridge:setControllerPowerSavingEnabled'),
                           subtitle=f'Caps light bar and trigger intensity at {POWER_SAVING_CAP}%'),
                  idle,
                  b.switch('Disconnect When Computer Sleeps', lambda s: dig(s, 'settings.usbSuspendDisconnectEnabled'),
                           self.setter('bridge:setUsbSuspendDisconnectEnabled'))),
            group('Notifications', None,
                  b.switch('Controller Connected', lambda s: dig(s, 'settings.notifyControllerConnection'),
                           self.setter('bridge:setNotifyControllerConnection')),
                  b.switch('Low Battery', lambda s: dig(s, 'settings.notifyLowBattery'),
                           self.setter('bridge:setNotifyLowBattery')),
                  b.switch('Microphone Muted', lambda s: dig(s, 'settings.notifyMicMute'),
                           self.setter('bridge:setNotifyMicMute')),
                  b.switch('Emulated Controller Changed', lambda s: dig(s, 'settings.notifyPersonaChange'),
                           self.setter('bridge:setNotifyPersonaChange')),
                  button_row('Test Notification', 'Send', lambda: self.call('bridge:testNotification'))),
            group('Startup', None,
                  b.switch('Run in Background at Login', lambda s: dig(s, 'settings.launchAtStartupEnabled'),
                           self.setter('bridge:setLaunchAtStartupEnabled'),
                           subtitle='Keeps haptics, audio and the Quick Settings tile working without this window')),
            group('Firmware', None,
                  button_row('Update Firmware', 'Choose File…', self._flash_firmware,
                             subtitle='Flash a DS5 Bridge UF2 onto the Pico'),
                  button_row('Bootloader Mode', 'Enter', lambda: self.call(
                      'bridge:mountPicoBootloader', done=lambda r: self.toast(r.get('message', '')) if r else None),
                      subtitle='Mount the Pico as a USB drive'),
                  button_row('Erase Pico Flash', 'Erase…', self._nuke, style='destructive-action',
                             subtitle='Recovery only: wipes the Pico so a bad firmware can be replaced')),
        )

    def _nuke(self):
        self._confirm('Erase Pico Flash?',
                      'This copies the bundled Pico Universal Flash Nuke UF2 to the mounted Pico bootloader drive '
                      'and erases the Pico flash.\n\nThe bridge will not work again until you flash the DS5 Bridge '
                      'firmware back onto it. Use this only to recover from a bad or stuck firmware install.',
                      'Erase', lambda: self.call('daemon:nukePicoFlashConfirmed',
                                                 done=lambda r: self.toast(r.get('message', '')) if r else None))

    def _flash_firmware(self):
        dialog = Gtk.FileDialog(title='Choose Pico Firmware')
        uf2 = Gtk.FileFilter(name='UF2 firmware')
        uf2.add_pattern('*.uf2')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(uf2)
        dialog.set_filters(filters)

        def chosen(dlg, result):
            try:
                file = dlg.open_finish(result)
            except GLib.Error:
                return
            self.toast('Flashing firmware…')
            self.call('daemon:flashPicoFirmwareFile', file.get_path(),
                      done=lambda r: self.toast(r.get('message', '')) if r else None)
        dialog.open(self, None, chosen)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.daemon = None
        for name, fn in (('classic', self._classic), ('about', self._about), ('quit', lambda: self.quit())):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, fn=fn: fn())
            self.add_action(action)
        self.set_accels_for_action('app.quit', ['<Control>q'])
        self.set_accels_for_action('window.close', ['<Control>w'])

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_string('''
            .ds5-pill { border-radius: 6px; padding: 3px 4px; background: alpha(currentColor, 0.1); }
            row.ds5-remapped .subtitle { color: var(--accent-color); opacity: 1; }
            .ds5-chip { padding: 8px 4px; border-radius: 12px; opacity: 0.4; }
            .ds5-chip.pressed { opacity: 1; background: alpha(var(--accent-bg-color), 0.3); }
        ''')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        window = self.get_active_window()
        if not window:
            self.daemon = self.daemon or Daemon()
            window = Window(self, self.daemon)
        window.present()
        # Dev only: DS5_GTK_SNAPSHOT=/path/prefix renders every page to PNG, then quits.
        prefix = os.environ.get('DS5_GTK_SNAPSHOT')
        if prefix:
            GLib.timeout_add(1500, self._dev_snapshots, window, prefix)

    def _dev_snapshots(self, window, prefix):
        keys = [key for key, *_ in window.pages]

        def render_now(name, target=None):
            target = target or window
            paintable = Gtk.WidgetPaintable(widget=target)
            snapshot = Gtk.Snapshot()
            paintable.snapshot(snapshot, target.get_width(), target.get_height())
            node = snapshot.to_node()
            if node:
                target.get_renderer().render_texture(node, None).save_to_png(f'{prefix}-{name}.png')

        def iter_widgets(widget):
            stack = [widget]
            while stack:
                w = stack.pop()
                yield w
                child = w.get_first_child()
                while child is not None:
                    stack.append(child)
                    child = child.get_next_sibling()

        def scroll_bottom(widget):
            child = widget
            while child is not None and not isinstance(child, Gtk.ScrolledWindow):
                child = child.get_first_child()
            if child:
                adj = child.get_vadjustment()
                adj.set_value(adj.get_upper())

        def dialogs():
            steps = [
                lambda: window._edit_chord_function(None),
                lambda: render_now('d1-new-function'),
                lambda: window._last_dialog_save.emit('clicked'),
                lambda: window._edit_chord_assignment(None),
                lambda: render_now('d2-new-chord'),
                lambda: window._last_dialog_save.emit('clicked'),
                lambda: (window.trigger_editors['both']._set_effect(default_trigger_effect('zoned-feedback')),
                         window.trigger_editors['both'].load(), window.stack.set_visible_child_name('triggers')),
                lambda: scroll_bottom(window.stack.get_child_by_name('triggers')),
                lambda: render_now('d0-trigger-editor'),
                lambda: window.stack.set_visible_child_name('sticks'),
                lambda: window._calibrate(CAL_CENTRE),
                lambda: None, lambda: None, lambda: None,
                lambda: render_now('d3-centre-done'),
                lambda: window._calibrate(CAL_RANGE),
                lambda: None, lambda: None, lambda: None,
                lambda: render_now('d4-sweep'),
                *[lambda: None] * 4,
                lambda: print('finish sensitive:', window._sweep_finish.get_sensitive(), flush=True),
                lambda: window._sweep_finish.emit('clicked') if window._sweep_finish.get_sensitive() else None,
                lambda: None, lambda: None,
                lambda: render_now('d5-range-done'),
                lambda: window.daemon.call('daemon:setHapticsMix', True),
                lambda: window.stack.set_visible_child_name('haptics'),
                lambda: [e.set_expanded(True) for e in iter_widgets(window.stack.get_child_by_name('haptics'))
                         if isinstance(e, Adw.ExpanderRow)],
                lambda: scroll_bottom(window.stack.get_child_by_name('haptics')),
                lambda: render_now('d6-haptics-mix'),
                lambda: window._edit_exclusions(lambda m: None),
                lambda: None,
                lambda: render_now('d7-exclusions'),
                lambda: window._last_dialog_save.emit('clicked'),
                lambda: window.stack.set_visible_child_name('devices'),
                lambda: render_now('d8-devices'),
                lambda: window.open_tester(),
                lambda: None, lambda: None,
                lambda: render_now('d9-tester', window.tester),
                lambda: self.quit(),
            ]
            for i, step in enumerate(steps):
                GLib.timeout_add(1200 * (i + 1), lambda st=step: (st(), GLib.SOURCE_REMOVE)[1])

        def shoot(index):
            if index >= len(keys):
                window.stack.set_visible_child_name('chords')
                window.content_page.set_title('Chords')
                dialogs()
                return GLib.SOURCE_REMOVE
            window.stack.set_visible_child_name(keys[index])
            window.content_page.set_title(window.pages[index][1])

            def render():
                width, height = window.get_width(), window.get_height()
                paintable = Gtk.WidgetPaintable(widget=window)
                snapshot = Gtk.Snapshot()
                paintable.snapshot(snapshot, width, height)
                node = snapshot.to_node()
                if node:
                    window.get_renderer().render_texture(node, None).save_to_png(f'{prefix}-{index}-{keys[index]}.png')
                GLib.timeout_add(100, shoot, index + 1)
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(600, render)
            return GLib.SOURCE_REMOVE
        shoot(0)
        return GLib.SOURCE_REMOVE

    def _classic(self):
        Gio.Subprocess.new([CLASSIC_UI], Gio.SubprocessFlags.NONE)

    def _about(self):
        version = ''
        if self.daemon and self.daemon.running:
            version = self.daemon.proxy.get_cached_property('UpstreamVersion')
            version = version.unpack() if version else ''
        about = Adw.AboutDialog(
            application_name='DS5 Bridge', application_icon='ds5-bridge',
            version=f'{version} (GNOME)' if version else 'GNOME',
            developer_name='SundayMoments, djanice1980',
            comments='Wireless DualSense through a Raspberry Pi Pico 2 W, with haptics, audio and adaptive triggers.',
            website='https://github.com/djanice1980/DS5_Bridge',
            issue_url='https://github.com/djanice1980/DS5_Bridge/issues',
            license_type=Gtk.License.AGPL_3_0_ONLY)
        about.present(self.get_active_window())


if __name__ == '__main__':
    sys.exit(App().run(sys.argv))
