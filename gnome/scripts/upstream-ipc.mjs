// Parses the upstream companion's IPC surface straight from its source, so the
// GNOME layer follows upstream without hand-maintained channel lists.
//
//  - preload.ts   -> every channel the upstream renderer can invoke
//  - main.ts      -> every ipcMain.handle(...) body, classified as:
//      generic : the body only forwards to service.<channelSuffix>(...)
//                -> the daemon dispatches it automatically
//      custom  : anything else -> must be implemented by hand in the daemon
//                or the client; its body hash is locked so upstream changes
//                to it get flagged for review.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const repoRoot = path.resolve(here, '..', '..');
const companionSrc = path.join(repoRoot, 'companion', 'src');

export function readUpstream(relative) {
  return fs.readFileSync(path.join(companionSrc, relative), 'utf8');
}

export function parsePreloadChannels(source = readUpstream('preload.ts')) {
  const channels = new Set();
  for (const match of source.matchAll(/ipcRenderer\.invoke\(\s*'([^']+)'/g)) {
    channels.add(match[1]);
  }
  const events = new Set();
  for (const match of source.matchAll(/ipcRenderer\.on\(\s*'([^']+)'/g)) {
    events.add(match[1]);
  }
  return { channels: [...channels].sort(), events: [...events].sort() };
}

function normalize(code) {
  return code.replace(/\s+/g, ' ').trim();
}

function hash(code) {
  return crypto.createHash('sha256').update(normalize(code)).digest('hex').slice(0, 16);
}

/** Body of `function registerIpc(...) { ... }`, by brace matching. */
function registerIpcBody(source) {
  const start = source.indexOf('function registerIpc(');
  if (start < 0) throw new Error('upstream main.ts: registerIpc() not found');
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, i);
    }
  }
  throw new Error('upstream main.ts: unbalanced registerIpc()');
}

// `(_event, a: T, b?: U) => service.name(a, b)` with optional wrapping parens
// and optional Boolean(...) coercions on arguments.
const GENERIC_HANDLER = /^\(\s*(?:_event(?:\s*,[^)]*)?)?\)\s*=>\s*\(?\s*service\.(\w+)\(([^()]*|(?:[^()]*Boolean\([^()]*\)[^()]*)*)\)\s*\)?\s*$/;

export function parseMainHandlers(source = readUpstream('main/main.ts')) {
  const body = registerIpcBody(source);
  const starts = [...body.matchAll(/ipcMain\.handle\(\s*'([^']+)'\s*,/g)];
  const handlers = {};
  starts.forEach((match, index) => {
    const channel = match[1];
    const from = match.index + match[0].length;
    const to = index + 1 < starts.length ? starts[index + 1].index : body.length;
    // Strip the trailing `);` that closes ipcMain.handle(.
    const code = body.slice(from, to).trim().replace(/\)\s*;\s*$/, '').trim();
    const suffix = channel.split(':')[1] ?? channel;
    const generic = GENERIC_HANDLER.exec(normalize(code));
    handlers[channel] = generic && generic[1] === suffix
      ? { kind: 'generic', method: suffix }
      : { kind: 'custom', hash: hash(code), code: normalize(code) };
  });
  return handlers;
}

/** Events BridgeService emits that upstream main.ts listens to. */
export function parseServiceEvents(source = readUpstream('main/main.ts')) {
  return [...new Set([...source.matchAll(/bridgeService\.on\(\s*'([^']+)'/g)].map((m) => m[1]))].sort();
}

/** Constructor signature of BridgeService, to catch new dependencies. */
export function parseServiceConstructor(source = readUpstream('main/bridge-service.ts')) {
  const match = /export class BridgeService[\s\S]*?constructor\(([\s\S]*?)\)\s*\{/.exec(source);
  if (!match) throw new Error('upstream bridge-service.ts: constructor not found');
  return normalize(match[1]);
}
