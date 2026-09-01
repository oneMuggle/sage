import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const configSource = readFileSync(resolve(process.cwd(), 'vite.config.ts'), 'utf8');

describe('local development server binding', () => {
  it('binds Vite dev, preview, and Vitest API servers to loopback', () => {
    expect(configSource).toMatch(/server:\s*\{[\s\S]*?host:\s*'127\.0\.0\.1'/);
    expect(configSource).toMatch(/preview:\s*\{[\s\S]*?host:\s*'127\.0\.0\.1'/);
    expect(configSource).toMatch(/test:\s*\{[\s\S]*?api:\s*\{\s*host:\s*'127\.0\.0\.1'/);
  });
});
