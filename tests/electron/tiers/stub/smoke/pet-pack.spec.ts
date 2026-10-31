import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { test, expect, type ElectronApplication } from '@playwright/test';

import { launchElectronWithStub } from '../../../helpers/electron-launcher';

// 1×1 transparent PNG — enough to prove the protocol serves bytes.
const ONE_PIXEL_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

// Reuse a small real WebM from the built-in pack to exercise media loading
// (metadata + range requests) over sage-pet:// in Chromium, without ffmpeg.
const SAMPLE_WEBM = join(process.cwd(), 'public', 'pet', 'dafeiyu', '工作状态-垂头叹气冒汗.webm');

const MANIFEST = {
  id: 'e2e-pet',
  name: 'E2E 小叶灵',
  version: '1.0.0',
  license: 'MIT',
  canvas: { width: 256, height: 256 },
  anchor: { x: 128, y: 236 },
  actions: {
    idle: ['frames/idle.webm'],
    thinking: ['frames/idle.png'],
  },
};

async function waitForPetWindow(
  app: ElectronApplication,
  timeoutMs = 15_000,
): Promise<import('@playwright/test').Page> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const found = app.windows().find((window) => window.url().includes('pet.html'));
    if (found) return found;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('pet window did not open');
}

test('pet pack: user packs are listed and served via sage-pet://', async () => {
  const userData = mkdtempSync(join(tmpdir(), 'sage-pet-e2e-'));
  const packDir = join(userData, 'pets', 'e2e-pet');
  mkdirSync(join(packDir, 'frames'), { recursive: true });
  writeFileSync(join(packDir, 'pack.json'), JSON.stringify(MANIFEST));
  writeFileSync(join(packDir, 'frames', 'idle.png'), ONE_PIXEL_PNG);
  writeFileSync(join(packDir, 'frames', 'idle.webm'), readFileSync(SAMPLE_WEBM));

  const { app, page, stub } = await launchElectronWithStub({
    env: { SAGE_USER_DATA_DIR: userData },
  });

  try {
    await page.waitForLoadState('load');
    const packs = await page.evaluate(async () => {
      const bridge = window.electronAPI?.pet;
      return bridge ? bridge.listPacks() : [];
    });
    expect(packs.map((pack) => pack.id)).toContain('e2e-pet');
    expect(packs[0]?.name).toBe('E2E 小叶灵');

    const served = await page.evaluate(async () => {
      return await new Promise<boolean>((resolve) => {
        const image = new Image();
        image.onload = () => resolve(image.naturalWidth === 1);
        image.onerror = () => resolve(false);
        image.src = 'sage-pet://e2e-pet/frames/idle.png';
      });
    });
    expect(served).toBe(true);

    const escaped = await page.evaluate(async () => {
      return await new Promise<boolean>((resolve) => {
        const image = new Image();
        image.onload = () => resolve(true);
        image.onerror = () => resolve(false);
        image.src = 'sage-pet://e2e-pet/%2e%2e/%2e%2e/package.json';
      });
    });
    expect(escaped).toBe(false);

    // Enable the pet with the imported pack; the overlay must load its video
    // from sage-pet:// and reach at least metadata-ready (range support).
    await page.evaluate(async () => {
      await window.electronAPI?.pet?.setConfig({
        enabled: true,
        displayMode: 'desktop',
        petPack: 'e2e-pet',
        compatibilityMode: 'on',
      });
    });
    const pet = await waitForPetWindow(app);
    await pet.waitForLoadState('domcontentloaded');
    const media = await pet
      .waitForFunction(
        () => {
          const video = document.querySelector('video');
          if (!video || !video.src.startsWith('sage-pet://e2e-pet/')) return false;
          if (video.readyState < 1 && !video.error) return false;
          return {
            readyState: video.readyState,
            error: video.error?.code ?? null,
            duration: video.duration,
          };
        },
        null,
        { timeout: 20_000 },
      )
      .then((handle) => handle.jsonValue());
    expect(media.error).toBeNull();
    expect(media.readyState).toBeGreaterThanOrEqual(1);
    expect(media.duration).toBeGreaterThan(0);
  } finally {
    await app.close();
    stub.stop();
    rmSync(userData, { recursive: true, force: true });
  }
});
