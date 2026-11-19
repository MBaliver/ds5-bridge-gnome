// Reaps pw-play / pw-record / pw-cat streams left behind by a dead AudioHelper
// (GNOME layer, not upstream).
//
// Upstream's Linux AudioHelper owns the pw-record/pw-play pair that carries audio-reactive
// haptics; only the helper's own shutdown path reaps them. If the helper dies another way
// (SIGKILL escalation, crash, or the controller powering off so the bridge re-enumerates as
// pid 0x0ce7 and a new helper takes over), the pair is orphaned. They keep a stream on the
// controller's ALSA sink after the card is gone, and PipeWire retries that dead device
// ~20 times a second until it runs out of file descriptors -- then no app can play audio at
// all. (Seen on 2026-11-18: orphans from 18:49, card gone 19:21, PipeWire dead by 21:46.)
//
// Re-parented orphans stay in this service's cgroup, so they are found exactly: an audio
// child in our cgroup whose parent is no longer in our cgroup has no owner.
import fs from 'node:fs';

const REAP_MS = 5000;
const AUDIO_CHILDREN = new Set(['pw-play', 'pw-record', 'pw-cat']);

function ownCgroupProcsPath(): string | null {
  try {
    // cgroup v2: a single "0::/path" line.
    const line = fs.readFileSync('/proc/self/cgroup', 'utf8').split('\n').find((l) => l.startsWith('0::'));
    if (!line) return null;
    const rel = line.slice(3).trim();
    // Running outside a dedicated unit (dev shell) would make the whole session our "cgroup".
    if (!rel.endsWith('.service') || !rel.includes('ds5-bridged')) return null;
    return `/sys/fs/cgroup${rel}/cgroup.procs`;
  } catch {
    return null;
  }
}

function readStat(pid: number): { comm: string; ppid: number } | null {
  try {
    const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
    // comm is parenthesised and may contain spaces; fields after the last ')' are fixed.
    const close = stat.lastIndexOf(')');
    const comm = stat.slice(stat.indexOf('(') + 1, close);
    const ppid = Number(stat.slice(close + 2).split(' ')[1]);
    return { comm, ppid };
  } catch {
    return null;
  }
}

/** Kill orphaned audio children once; returns the pids signalled. */
export function reapOrphanedAudio(procsPath: string): number[] {
  let pids: number[];
  try {
    pids = fs.readFileSync(procsPath, 'utf8').split('\n').filter(Boolean).map(Number);
  } catch {
    return [];
  }
  const members = new Set(pids);
  const reaped: number[] = [];
  for (const pid of pids) {
    const stat = readStat(pid);
    if (!stat || !AUDIO_CHILDREN.has(stat.comm) || members.has(stat.ppid)) continue;
    try {
      process.kill(pid, 'SIGTERM');
      reaped.push(pid);
      // pw-cat ignores nothing, but a wedged PipeWire connection can stall its exit.
      setTimeout(() => {
        try { process.kill(pid, 'SIGKILL'); } catch { /* already gone */ }
      }, 2000).unref();
    } catch {
      // Exited in between.
    }
  }
  return reaped;
}

export function startOrphanReaper(): () => void {
  const procsPath = ownCgroupProcsPath();
  if (!procsPath) {
    console.log('[orphan-reaper] not running in the ds5-bridged unit cgroup; disabled');
    return () => {};
  }
  const tick = () => {
    const reaped = reapOrphanedAudio(procsPath);
    if (reaped.length) console.warn(`[orphan-reaper] stopped orphaned audio streams: ${reaped.join(', ')}`);
  };
  tick();
  const timer = setInterval(tick, REAP_MS);
  timer.unref();
  return () => clearInterval(timer);
}
