/**
 * tests/packaging/verify-artifacts.spec.ts
 *
 * Validates that electron-builder produced the expected distributables
 * for the current package.json version. Run AFTER:
 *   npm run electron:build
 *   npx electron-builder --linux AppImage deb --publish never
 *
 * In the default vitest run (npm test / npm run test:coverage) this suite
 * is GUARDED by `describe.skipIf(!existsSync(releaseDir))` — when artifacts
 * haven't been built (typical `npm install` checkout, CI lint job) the whole
 * suite is skipped, keeping frontend test runs hermetic. When artifacts are
 * present (e.g. after `npm run electron:dist`) it runs as a real verifier.
 * Invoke explicitly:
 *   npx vitest run tests/packaging/   (or `npm run test:packaging`)
 */
import { describe, expect, it } from 'vitest';
import { existsSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import pkg from '../../package.json';

const { version } = pkg;
const releaseDir = resolve(__dirname, `../../release/${version}`);

/** Minimum sensible artifact size — Electron baseline ~80MB; 50MB catches truncated/empty builds. */
const MIN_ARTIFACT_SIZE_BYTES = 50 * 1024 * 1024;

describe.skipIf(!existsSync(releaseDir))('packaging artifacts', () => {
  it('Linux AppImage exists and >= 50MB', () => {
    const appimage = resolve(releaseDir, `Sage-${version}.AppImage`);
    expect(existsSync(appimage), `missing ${appimage}`).toBe(true);
    expect(statSync(appimage).size).toBeGreaterThan(MIN_ARTIFACT_SIZE_BYTES);
  });

  it('Linux deb exists and >= 50MB', () => {
    const deb = resolve(releaseDir, `sage_${version}_amd64.deb`);
    expect(existsSync(deb), `missing ${deb}`).toBe(true);
    expect(statSync(deb).size).toBeGreaterThan(MIN_ARTIFACT_SIZE_BYTES);
  });
});
