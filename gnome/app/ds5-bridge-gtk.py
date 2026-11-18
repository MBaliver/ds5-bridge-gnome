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
MUTE_MODES = [('normal', 'Mute Microphone'), ('quiet', 'Quiet Mode'),
              ('keyboard', 'Keyboard Key'), ('chord', 'Chord Starter')]
TRIGGER_TESTS = [('feedback', 'Feedback'), ('weapon', 'Weapon'), ('vibration', 'Vibration')]
REACTIVE_SOURCES = [('system-audio', 'System Audio'), ('controller-audio', 'Controller Audio')]
REACTIVE_MODES = [('mix', 'Mix With Game Haptics'), ('replace', 'Replace Game Haptics')]
BASS_FOCUS = [('deep', 'Deep'), ('balanced', 'Balanced'), ('punchy', 'Punchy'), ('wide', 'Wide')]
RESPONSE = [('subtle', 'Subtle'), ('balanced', 'Balanced'), ('strong', 'Strong')]
ATTACK = [('soft', 'Soft'), ('balanced', 'Balanced'), ('fast', 'Fast'), ('sharp', 'Sharp')]
RELEASE = [('tight', 'Tight'), ('balanced', 'Balanced'), ('smooth', 'Smooth'), ('long', 'Long')]
# Same limits as the upstream UI (App.tsx).
STANDARD_FEEDBACK_MAX = 200
BOOSTED_FEEDBACK_MAX = 500
POWER_SAVING_CAP = 60


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

    def call(self, channel, *args, done=None, quiet=False):
        def finish(proxy, result):
            try:
                (text,) = proxy.call_finish(result).unpack()
            except GLib.Error as error:
                message = Gio.DBusError.get_remote_error(error) and error.message.split(': ', 1)[-1] or error.message
                if not quiet:
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


# ----------------------------------------------------------------- window

class Window(Adw.ApplicationWindow):
    def __init__(self, app, daemon):
        super().__init__(application=app, title='DS5 Bridge', default_width=980, default_height=720)
        self.set_size_request(360, 400)
        self.daemon = daemon
        self.snapshot = None
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
            ('triggers', 'Triggers & Sticks', 'find-location-symbolic', self._page_triggers),
            ('lighting', 'Lighting', 'display-brightness-symbolic', self._page_lighting),
            ('buttons', 'Buttons', 'input-keyboard-symbolic', self._page_buttons),
            ('system', 'System', 'emblem-system-symbolic', self._page_system),
        ]

        sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        sidebar.add_css_class('navigation-sidebar')
        for key, title, icon, build in self.pages:
            page = build()
            self.stack.add_named(page, key)
            box = Gtk.Box(spacing=12)
            box.append(Gtk.Image(icon_name=icon))
            box.append(Gtk.Label(label=title, xalign=0))
            row = Gtk.ListBoxRow(child=box)
            row._key, row._title = key, title
            sidebar.append(row)
        sidebar.connect('row-activated', self._on_sidebar)

        menu = Gio.Menu()
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

    def _page_controller(self):
        b = self.b
        connected = lambda s: dig(s, 'status.controllerConnected')  # noqa: E731

        # Hero, in the spirit of Settings' device pages.
        icon = Gtk.Image(icon_name='input-gaming-symbolic', pixel_size=96)
        icon.add_css_class('dim-label')
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

        profile_ids = []
        profiles = Adw.ComboRow(title='Profile', subtitle='Settings that follow this controller')
        profiles.set_model(Gtk.StringList())

        def on_profile(*_):
            if not b.syncing and profiles.get_selected() < len(profile_ids):
                self.call('bridge:selectControllerProfile', profile_ids[profiles.get_selected()])
        profiles.connect('notify::selected', on_profile)

        def profiles_sync(s):
            items = dig(s, 'settings.controllerProfiles', [])
            ids = [p['id'] for p in items]
            if ids != profile_ids or [p['name'] for p in items] != [
                    profiles.get_model().get_string(i) for i in range(profiles.get_model().get_n_items())]:
                profile_ids[:] = ids
                profiles.set_model(Gtk.StringList.new([p['name'] for p in items]))
            current = dig(s, 'settings.selectedControllerProfileId')
            if current in profile_ids:
                profiles.set_selected(profile_ids.index(current))
        b.syncers.append(profiles_sync)

        def current_profile():
            i = profiles.get_selected()
            items = dig(self.snapshot, 'settings.controllerProfiles', [])
            return items[i] if 0 <= i < len(items) else None

        actions = Gio.SimpleActionGroup()
        for name, fn in {
            'save-new': lambda: self._ask_name('New Profile', '', 'Save',
                                               lambda n: self.call('bridge:saveControllerProfile', n)),
            'update': lambda: (p := current_profile()) and self.call('bridge:updateControllerProfile', p['id'],
                                                                     done=lambda _: self.toast(f'“{p["name"]}” updated')),
            'rename': lambda: (p := current_profile()) and self._ask_name(
                'Rename Profile', p['name'], 'Rename', lambda n: self.call('bridge:renameControllerProfile', p['id'], n)),
            'delete': lambda: (p := current_profile()) and self._confirm(
                f'Delete “{p["name"]}”?', 'This profile will be removed permanently.', 'Delete',
                lambda: self.call('bridge:deleteControllerProfile', p['id'])),
        }.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, fn=fn: fn())
            actions.add_action(action)
        self.insert_action_group('profile', actions)
        profile_menu = Gio.Menu()
        profile_menu.append('Save Current Settings as New Profile…', 'profile.save-new')
        profile_menu.append('Update Profile With Current Settings', 'profile.update')
        section = Gio.Menu()
        section.append('Rename…', 'profile.rename')
        section.append('Delete…', 'profile.delete')
        profile_menu.append_section(None, section)
        profiles.add_suffix(Gtk.MenuButton(icon_name='view-more-symbolic', menu_model=profile_menu,
                                           valign=Gtk.Align.CENTER, tooltip_text='Profile Actions',
                                           css_classes=['flat']))

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
        known = Adw.PreferencesGroup(title='Paired Controllers')
        known_rows = []
        last = {'key': None}

        def known_sync(s):
            history = dig(s, 'settings.controllerHistory', []) or []
            key = json.dumps(history)
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
            for entry in history:
                mac = ':'.join(entry['mac'][i:i + 2] for i in range(0, len(entry['mac']), 2)).upper()
                seen = GLib.DateTime.new_from_unix_local(entry['lastSeenAt'] // 1000).format('%x %X')
                bits = [mac, f'last seen {seen}']
                if entry.get('lastBatteryPercent') is not None:
                    bits.append(f'{entry["lastBatteryPercent"]}%')
                row = Adw.ActionRow(title=controller_label(entry.get('controllerType')), subtitle=' · '.join(bits))
                row.add_prefix(Gtk.Image(icon_name='input-gaming-symbolic'))
                forget = Gtk.Button(icon_name='user-trash-symbolic', valign=Gtk.Align.CENTER,
                                    tooltip_text='Forget Controller', css_classes=['flat'])
                forget.connect('clicked', lambda _b, m=entry['mac'], label=mac: self._confirm(
                    f'Forget {label}?', 'The controller will need to be paired again.', 'Forget',
                    lambda: self.call('bridge:forgetControllerPairing', m)))
                row.add_suffix(forget)
                known.add(row)
                known_rows.append(row)
        b.syncers.append(known_sync)

        return self._page(
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
            b.combo('Source', REACTIVE_SOURCES, lambda s: dig(s, 'settings.audioReactiveHapticsSource'), reactive('source')),
            b.combo('Mode', REACTIVE_MODES, lambda s: dig(s, 'settings.audioReactiveHapticsMode'), reactive('mode')),
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

    def _page_triggers(self):
        b = self.b
        test_mode = {'value': 'feedback'}

        def deadzone(side):
            def send(value):
                left = dig(self.snapshot, 'settings.stickDeadzoneLeftPercent', 0)
                right = dig(self.snapshot, 'settings.stickDeadzoneRightPercent', 0)
                self.call('bridge:setStickDeadzone', value if side == 'left' else left,
                          value if side == 'right' else right)
            return send

        def set_test_mode(mode):
            test_mode['value'] = mode
            self.call('bridge:setTriggerTestMode', mode)

        power_cap = lambda s: POWER_SAVING_CAP if dig(s, 'settings.controllerPowerSavingEnabled') else 100  # noqa: E731
        return self._page(
            group('Adaptive Triggers', None,
                  b.switch('Adaptive Triggers', lambda s: dig(s, 'settings.adaptiveTriggersEnabled'),
                           self.setter('bridge:setAdaptiveTriggersEnabled')),
                  b.scale('Intensity', 0, 100, 10, lambda s: dig(s, 'settings.triggerEffectIntensityPercent'),
                          self.setter('bridge:setTriggerEffectIntensity'), max_fn=power_cap),
                  b.combo('Test Effect', TRIGGER_TESTS, lambda s: dig(s, 'settings.triggerTestMode'), set_test_mode),
                  button_row('Test Triggers', 'Test', lambda: self.call(
                      'bridge:testAdaptiveTriggers', dig(self.snapshot, 'settings.triggerTestMode', 'feedback'), 'both')),
                  button_row('Reset Triggers', 'Reset', lambda: self.call('bridge:resetAdaptiveTriggers'),
                             subtitle='Clear any effect a game left applied')),
            group('Stick Deadzone', 'Radial deadzone as a share of stick travel. 0 turns it off.',
                  b.spin('Left Stick', 0, 50, 1, lambda s: dig(s, 'settings.stickDeadzoneLeftPercent'), deadzone('left')),
                  b.spin('Right Stick', 0, 50, 1, lambda s: dig(s, 'settings.stickDeadzoneRightPercent'), deadzone('right'))),
            group(None, 'The trigger effect editor, stick calibration and live input tester are in the classic interface.',
                  button_row('Advanced Tools', 'Open', lambda: self.get_application().activate_action('classic'))),
        )

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

    def _page_buttons(self):
        b = self.b

        def set_mute_mode(mode):
            st = self.snapshot['settings']
            self.call('bridge:setMuteButtonAction', mode, st['muteKeyboardUsage'], st['muteKeyboardModifiers'],
                      st['muteKeyboardBehavior'], st['muteKeyboardChordStarterEnabled'])

        return self._page(
            group('Mute Button', None,
                  b.combo('Action', MUTE_MODES, lambda s: dig(s, 'settings.muteButtonMode'), set_mute_mode),
                  b.switch('Sleep Shortcut', lambda s: dig(s, 'settings.sleepKeybindEnabled'),
                           self.setter('bridge:setSleepKeybindEnabled'),
                           subtitle='Hold PS and Mute to turn the controller off')),
            group('Touchpad', None,
                  b.switch('Use Touchpad as Mouse', lambda s: dig(s, 'settings.touchpadMouseEnabled'),
                           self.setter('bridge:setTouchpadMouseEnabled'))),
            group(None, 'Button remapping, chord functions and keyboard keys for the mute button are in the classic '
                        'interface.',
                  button_row('Button Remapping', 'Open', lambda: self.get_application().activate_action('classic'))),
        )

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
                      subtitle='Mount the Pico as a USB drive')),
        )

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

        def shoot(index):
            if index >= len(keys):
                self.quit()
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
