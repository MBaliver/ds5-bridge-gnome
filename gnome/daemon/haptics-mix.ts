// "All apps except…" source for audio-reactive haptics (GNOME layer feature, not upstream).
//
// Upstream can drive haptics from ONE source: system audio, one output device (a PipeWire
// sink's monitor) or one app. This builds a dedicated null sink, "DS5 Haptics Mix", and fans
// a copy of every app's output stream into it -- except the apps the user excluded (voice
// chat, music, browsers). Apps keep playing to their normal output: PipeWire lets one output
// port link to several inputs. Upstream's own output-device source then captures the mix.
//
// The link set is reconciled from pw-dump on a timer, so apps that start later (a game) are
// picked up automatically.
import { execFile, execFileSync } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
// A wedged PipeWire must never pin a reconcile (or the D-Bus call behind it) forever.
const COMMAND_TIMEOUT_MS = 5000;
const run = (file: string, args: string[], options: { maxBuffer?: number } = {}) =>
  execFileAsync(file, args, { ...options, timeout: COMMAND_TIMEOUT_MS, killSignal: 'SIGKILL' });

export const MIX_SINK_NAME = 'ds5-haptics-mix';
export const MIX_SINK_DESCRIPTION = 'DS5 Haptics Mix';
const RECONCILE_MS = 1500;

/** Our own audio plumbing must never feed back into the mix. */
const IGNORED_BINARIES = new Set(['audiohelper', 'pw-play', 'pw-record', 'pw-cat', 'pw-loopback']);

export interface MixApp {
  /** Lowercased process binary, or application name when there is no binary. */
  key: string;
  name: string;
}

export interface MixStream extends MixApp {
  included: boolean;
}

type PwObject = {
  id: number;
  type: string;
  info?: { props?: Record<string, unknown>; 'output-port-id'?: number; 'input-port-id'?: number };
};

function appOf(props: Record<string, unknown>): MixApp | null {
  const binary = typeof props['application.process.binary'] === 'string' ? props['application.process.binary'] as string : '';
  const appName = typeof props['application.name'] === 'string' ? props['application.name'] as string : '';
  const nodeName = typeof props['node.name'] === 'string' ? props['node.name'] as string : '';
  const key = (binary || appName || nodeName).toLowerCase();
  if (!key) return null;
  return { key, name: appName || binary || nodeName };
}

// Fold any layout into the mix's stereo pair: left-ish -> FL, right-ish -> FR, the rest -> both.
function targetChannels(channel: string): string[] {
  if (['FL', 'RL', 'SL', 'FLC', 'RLC', 'TFL', 'TRL'].includes(channel)) return ['FL'];
  if (['FR', 'RR', 'SR', 'FRC', 'RRC', 'TFR', 'TRR'].includes(channel)) return ['FR'];
  return ['FL', 'FR'];
}

export class HapticsMix {
  private moduleId: string | null = null;
  private timer: NodeJS.Timeout | null = null;
  private excluded = new Set<string>();
  private reconciling = false;
  streams: MixStream[] = [];

  get running(): boolean {
    return this.moduleId !== null;
  }

  async start(excluded: MixApp[]): Promise<void> {
    this.setExcluded(excluded);
    if (!this.moduleId) {
      await this.unloadStale();
      const { stdout } = await run('pactl', [
        'load-module', 'module-null-sink',
        `sink_name=${MIX_SINK_NAME}`,
        'channel_map=front-left,front-right',
        `sink_properties=device.description="${MIX_SINK_DESCRIPTION}"`
      ]);
      this.moduleId = stdout.trim();
    }
    if (!this.timer) {
      this.timer = setInterval(() => void this.reconcile(), RECONCILE_MS);
    }
    await this.reconcile();
  }

  setExcluded(excluded: MixApp[]): void {
    this.excluded = new Set(excluded.map((app) => app.key.toLowerCase()));
  }

  async stop(): Promise<void> {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (this.moduleId) {
      await run('pactl', ['unload-module', this.moduleId]).catch(() => {});
      this.moduleId = null;
    }
    this.streams = [];
  }

  /** Synchronous best effort for process exit. */
  stopSync(): void {
    if (this.moduleId) {
      try { execFileSync('pactl', ['unload-module', this.moduleId], { timeout: COMMAND_TIMEOUT_MS }); } catch { /* gone already */ }
      this.moduleId = null;
    }
  }

  /** A crash can leave our sink behind; never stack a second one. */
  private async unloadStale(): Promise<void> {
    const { stdout } = await run('pactl', ['list', 'short', 'modules']).catch(() => ({ stdout: '' }));
    for (const line of stdout.split('\n')) {
      if (line.includes('module-null-sink') && line.includes(`sink_name=${MIX_SINK_NAME}`)) {
        await run('pactl', ['unload-module', line.split('\t')[0]]).catch(() => {});
      }
    }
  }

  /** Current app streams, for the UI, even when the mix is off. */
  async listStreams(): Promise<MixStream[]> {
    const objects = await this.dump();
    return this.appStreams(objects).map(({ app }) => ({ ...app, included: !this.excluded.has(app.key) }))
      .filter((s, i, all) => all.findIndex((o) => o.key === s.key) === i);
  }

  private async dump(): Promise<PwObject[]> {
    const { stdout } = await run('pw-dump', [], { maxBuffer: 64 * 1024 * 1024 });
    return JSON.parse(stdout) as PwObject[];
  }

  private appStreams(objects: PwObject[]): Array<{ id: number; app: MixApp }> {
    const out: Array<{ id: number; app: MixApp }> = [];
    for (const o of objects) {
      const props = o.info?.props ?? {};
      if (o.type !== 'PipeWire:Interface:Node' || props['media.class'] !== 'Stream/Output/Audio') continue;
      const app = appOf(props);
      if (!app || IGNORED_BINARIES.has(app.key) || app.key.includes('ds5')) continue;
      out.push({ id: o.id, app });
    }
    return out;
  }

  private async reconcile(): Promise<void> {
    if (this.reconciling || !this.moduleId) return;
    this.reconciling = true;
    try {
      const objects = await this.dump();
      const sink = objects.find((o) => o.type === 'PipeWire:Interface:Node'
        && o.info?.props?.['node.name'] === MIX_SINK_NAME);
      if (!sink) return;
      const ports = objects.filter((o) => o.type === 'PipeWire:Interface:Port');
      const sinkInputs = new Map<string, number>();
      for (const port of ports) {
        const p = port.info?.props ?? {};
        if (p['node.id'] === sink.id && p['port.direction'] === 'in') {
          sinkInputs.set(String(p['audio.channel']), port.id);
        }
      }
      const streams = this.appStreams(objects);
      this.streams = streams.map(({ app }) => ({ ...app, included: !this.excluded.has(app.key) }))
        .filter((s, i, all) => all.findIndex((o) => o.key === s.key) === i);

      const wanted = new Set<string>();
      for (const { id, app } of streams) {
        if (this.excluded.has(app.key)) continue;
        for (const port of ports) {
          const p = port.info?.props ?? {};
          if (p['node.id'] !== id || p['port.direction'] !== 'out') continue;
          // Skip monitor ports; only real outputs.
          if (p['port.monitor'] === true) continue;
          for (const channel of targetChannels(String(p['audio.channel'] ?? 'MONO'))) {
            const input = sinkInputs.get(channel);
            if (input !== undefined) wanted.add(`${port.id}:${input}`);
          }
        }
      }
      const inputIds = new Set(sinkInputs.values());
      const existing = new Set<string>();
      for (const link of objects.filter((o) => o.type === 'PipeWire:Interface:Link')) {
        const out = link.info?.['output-port-id'];
        const input = link.info?.['input-port-id'];
        if (out !== undefined && input !== undefined && inputIds.has(input)) existing.add(`${out}:${input}`);
      }
      for (const pair of wanted) {
        if (!existing.has(pair)) {
          const [out, input] = pair.split(':');
          await run('pw-link', [out, input]).catch(() => {});
        }
      }
      for (const pair of existing) {
        if (!wanted.has(pair)) {
          const [out, input] = pair.split(':');
          await run('pw-link', ['-d', out, input]).catch(() => {});
        }
      }
    } catch (error) {
      console.warn('[haptics-mix] reconcile failed:', (error as Error).message);
    } finally {
      this.reconciling = false;
    }
  }
}
