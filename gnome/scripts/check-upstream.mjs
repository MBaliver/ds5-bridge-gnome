// Sync check against upstream. Run after `git merge upstream/main`.
//
// Exit 0: nothing needs a human. Exit 1: prints what changed upstream that the
// GNOME layer must look at. `--accept` rewrites the lock after you've handled it.
import fs from 'node:fs';
import path from 'node:path';
import {
  parseMainHandlers, parsePreloadChannels, parseServiceConstructor, parseServiceEvents, repoRoot
} from './upstream-ipc.mjs';

const lockPath = path.join(repoRoot, 'gnome', 'upstream-ipc.lock.json');
const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
const handlers = parseMainHandlers();
const { events } = parsePreloadChannels();
const serviceEvents = parseServiceEvents();
const ctor = parseServiceConstructor();
const problems = [];

for (const [channel, h] of Object.entries(handlers)) {
  if (h.kind !== 'custom') continue;
  const locked = lock.custom[channel];
  if (!locked) {
    problems.push(`NEW custom handler ${channel} -- implement it in the daemon or client, then add it to the lock:\n      ${h.code}`);
  } else if (locked.hash !== h.hash) {
    problems.push(`CHANGED custom handler ${channel} (owner: ${locked.owner}) -- port the change:\n      ${h.code}`);
  }
}
for (const channel of Object.keys(lock.custom)) {
  if (handlers[channel]?.kind !== 'custom') {
    problems.push(`REMOVED/now-generic custom handler ${channel} -- drop our override`);
  }
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
if (!same(events, lock.rendererEvents)) problems.push(`renderer push events changed: ${lock.rendererEvents} -> ${events}`);
if (!same(serviceEvents, lock.serviceEvents)) problems.push(`BridgeService events changed: ${lock.serviceEvents} -> ${serviceEvents}`);
if (ctor !== lock.serviceConstructor) problems.push(`BridgeService constructor changed:\n      ${lock.serviceConstructor}\n   -> ${ctor}`);

const generic = Object.values(handlers).filter((h) => h.kind === 'generic').length;
console.log(`${Object.keys(handlers).length} upstream channels: ${generic} generic (automatic), ${Object.keys(lock.custom).length} custom (locked)`);

if (process.argv.includes('--accept')) {
  const owners = Object.fromEntries(Object.entries(lock.custom).map(([c, v]) => [c, v.owner]));
  const custom = Object.fromEntries(Object.entries(handlers)
    .filter(([, h]) => h.kind === 'custom')
    .map(([c, h]) => [c, { owner: owners[c] ?? 'TODO', hash: h.hash }]));
  fs.writeFileSync(lockPath, JSON.stringify({ rendererEvents: events, serviceEvents, serviceConstructor: ctor, custom }, null, 2) + '\n');
  console.log('lock updated');
  process.exit(0);
}
if (problems.length) {
  console.log(`\n${problems.length} item(s) need attention:\n`);
  for (const p of problems) console.log(` - ${p}`);
  process.exit(1);
}
console.log('in sync');
