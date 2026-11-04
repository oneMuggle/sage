import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { test, expect } from '@playwright/test';

import { launchElectronWithStub } from '../../../helpers/electron-launcher';

const NOW_TIMEOUT = 15_000;

interface TokenFile {
  version: number;
  pid: number;
  port: number;
  token: string;
  createdAt: number;
}

async function waitForTokenFile(file: string): Promise<TokenFile> {
  const deadline = Date.now() + NOW_TIMEOUT;
  while (Date.now() < deadline) {
    if (existsSync(file)) {
      try {
        return JSON.parse(readFileSync(file, 'utf8')) as TokenFile;
      } catch {
        // Mid-write; retry.
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('pet-api.json was not written');
}

test('pet status API: loopback server starts on opt-in and stops on disable', async () => {
  const userData = mkdtempSync(join(tmpdir(), 'sage-pet-api-e2e-'));
  const tokenFile = join(userData, 'pet-api.json');
  const { app, page, stub } = await launchElectronWithStub({
    env: { SAGE_USER_DATA_DIR: userData },
  });

  try {
    await page.waitForLoadState('load');
    await page.evaluate(async () => {
      await window.electronAPI?.pet?.setConfig({ externalApi: true });
    });

    const info = await waitForTokenFile(tokenFile);
    expect(info.version).toBe(1);
    expect(info.port).toBeGreaterThan(0);
    expect(info.token).toMatch(/^[a-f0-9]{64}$/);

    const unauthorized = await fetch(`http://127.0.0.1:${info.port}/v1/status`);
    expect(unauthorized.status).toBe(401);

    const authorized = await fetch(`http://127.0.0.1:${info.port}/v1/status`, {
      headers: { Authorization: `Bearer ${info.token}` },
    });
    expect(authorized.status).toBe(200);
    const payload = (await authorized.json()) as { version: number; action: string };
    expect(payload.version).toBe(1);
    expect(typeof payload.action).toBe('string');

    const apiInfo = await page.evaluate(async () => window.electronAPI?.pet?.getApiInfo());
    expect(apiInfo).toMatchObject({ enabled: true, port: info.port, error: null });

    await page.evaluate(async () => {
      await window.electronAPI?.pet?.setConfig({ externalApi: false });
    });
    await expect.poll(() => existsSync(tokenFile), { timeout: NOW_TIMEOUT }).toBe(false);
    await expect
      .poll(
        () =>
          fetch(`http://127.0.0.1:${info.port}/v1/health`, {
            headers: { Authorization: `Bearer ${info.token}` },
          }).then(
            () => 'open',
            () => 'closed',
          ),
        { timeout: NOW_TIMEOUT },
      )
      .toBe('closed');
  } finally {
    await app.close();
    stub.stop();
    rmSync(userData, { recursive: true, force: true });
  }
});
