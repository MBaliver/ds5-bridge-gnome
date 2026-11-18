// Replaces Electron's safeStorage for BootloaderAuthorizationStore.
//
// A random 256-bit master key lives in the GNOME keyring (libsecret, via
// secret-tool); records are sealed with AES-256-GCM under it. The keyring is
// only touched when a bootloader key is actually read or written.
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import type { BootloaderAuthorizationProtectionPort } from '../../companion/src/main/bootloader-authorization-store';

const ATTRS = ['service', 'ds5-bridged', 'key', 'bootloader-master'];
const LABEL = 'DS5 Bridge bootloader authorization key';
const FORMAT = 'g1';

export class KeyringProtection implements BootloaderAuthorizationProtectionPort {
  private key: Buffer | null = null;

  isEncryptionAvailable(): boolean {
    try {
      this.masterKey();
      return true;
    } catch (error) {
      console.warn('[keyring] unavailable:', (error as Error).message);
      return false;
    }
  }

  encryptString(value: string): Buffer {
    const iv = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', this.masterKey(), iv);
    const body = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
    return Buffer.concat([Buffer.from(FORMAT), iv, cipher.getAuthTag(), body]);
  }

  decryptString(value: Buffer): string {
    if (value.subarray(0, 2).toString() !== FORMAT) {
      throw new Error('Unknown protected-storage format (was it written by the Electron app?).');
    }
    const iv = value.subarray(2, 14);
    const tag = value.subarray(14, 30);
    const decipher = crypto.createDecipheriv('aes-256-gcm', this.masterKey(), iv);
    decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(value.subarray(30)), decipher.final()]).toString('utf8');
  }

  private masterKey(): Buffer {
    if (this.key) return this.key;
    const lookup = spawnSync('secret-tool', ['lookup', ...ATTRS], { encoding: 'utf8' });
    if (lookup.error) throw lookup.error;
    const existing = lookup.stdout.trim();
    if (lookup.status === 0 && /^[0-9a-f]{64}$/.test(existing)) {
      this.key = Buffer.from(existing, 'hex');
      return this.key;
    }
    const fresh = crypto.randomBytes(32);
    const store = spawnSync('secret-tool', ['store', `--label=${LABEL}`, ...ATTRS], {
      input: fresh.toString('hex'),
      encoding: 'utf8'
    });
    if (store.error) throw store.error;
    if (store.status !== 0) throw new Error(`secret-tool store failed: ${store.stderr.trim()}`);
    this.key = fresh;
    return this.key;
  }
}
