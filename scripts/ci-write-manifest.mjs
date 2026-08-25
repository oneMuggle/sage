#!/usr/bin/env node
/*
 * CI helper — emit resources/build-manifest.json before electron-builder.
 *
 * Why: scripts/bundle-python-main.ps1 only runs on tag-driven release
 * workflows. CI does NOT call it; instead it runs `npm run electron:build`
 * then `npx electron-builder` directly. Without this manifest the
 * extraResources entry in electron-builder.yml has nothing to pick up,
 * and the packaged artifact is missing resources/build-manifest.json —
 * silently disabling buildId-based health-ownership validation.
 *
 * Mirror of the manifest block in scripts/bundle-python.ps1 (Win7 LTS)
 * and scripts/bundle-python-main.ps1. Field set is the BuildManifest
 * contract from electron/buildManifest.ts.
 *
 * Written as ESM (.mjs) because package.json has `"type": "module"` and
 * plain .js under scripts/ would also be ESM, but the @typescript-eslint
 * config rejects `require()` calls. Using `import` keeps both Node and
 * ESLint happy.
 */
import fs from 'node:fs';
import path from 'node:path';

const sha = process.env.GITHUB_SHA || 'unknown';
const sha7 = sha.slice(0, 7);
const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, 'Z');

const manifest = {
  manifestVersion: 1,
  buildId: process.env.SAGE_BUILD_ID || `ci-${sha7}-${stamp}`,
  commit: sha,
  branch: process.env.GITHUB_REF_NAME || 'unknown',
  version: process.env.SAGE_BUILD_VERSION || '0.0.0-ci',
  electronVersion: process.env.SAGE_ELECTRON_VERSION || '21.4.4',
  pythonVersion: process.env.SAGE_PYTHON_VERSION || '3.11.9',
};

const dir = path.join(process.env.GITHUB_WORKSPACE || process.cwd(), 'resources');
fs.mkdirSync(dir, { recursive: true });
const file = path.join(dir, 'build-manifest.json');
fs.writeFileSync(file, JSON.stringify(manifest, null, 2) + '\n');
console.log(`Wrote ${file}`);
console.log(fs.readFileSync(file, 'utf8'));
