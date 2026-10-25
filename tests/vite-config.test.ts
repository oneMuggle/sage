import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const configSource = readFileSync(resolve(process.cwd(), 'vite.config.ts'), 'utf8');

describe('local development server binding', () => {
  it('binds Vite dev and preview servers to loopback', () => {
    expect(configSource).toMatch(/server:\s*\{[\s\S]*?host:\s*'127\.0\.0\.1'/);
    expect(configSource).toMatch(/preview:\s*\{[\s\S]*?host:\s*'127\.0\.0\.1'/);
  });

  it('R121: Vitest API server 保持禁用（防 51204 僵尸端口阻断后续运行）', () => {
    // api: false 时 vitest 完全不起 API server —— 比 loopback 绑定更强的
    // 安全姿态（无监听即无暴露），且消除崩溃/中断运行残留端口进程的
    // 故障模式。此断言防止配置被改回启用。
    expect(configSource).toMatch(/test:\s*\{[\s\S]*?api:\s*false/);
    expect(configSource).not.toMatch(/test:\s*\{[\s\S]*?api:\s*\{/);
  });
});
