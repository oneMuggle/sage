import { describe, expect, it } from 'vitest';
import { existsSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import pkg from '../../package.json' assert { type: 'json' };

const version = pkg.version;
const releaseDir = resolve(__dirname, `../../release/${version}`);

describe('packaging artifacts', () => {
  it('Linux AppImage exists and >= 50MB', () => {
    const appimage = resolve(releaseDir, `Sage-${version}.AppImage`);
    expect(existsSync(appimage), `missing ${appimage}`).toBe(true);
    expect(statSync(appimage).size).toBeGreaterThan(50 * 1024 * 1024);
  });

  it('Linux deb exists and >= 50MB', () => {
    const deb = resolve(releaseDir, `sage_${version}_amd64.deb`);
    expect(existsSync(deb), `missing ${deb}`).toBe(true);
    expect(statSync(deb).size).toBeGreaterThan(50 * 1024 * 1024);
  });
});