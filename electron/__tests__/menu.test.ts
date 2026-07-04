// electron/__tests__/menu.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { join } from 'node:path';

const mocks = vi.hoisted(() => ({
  Menu: {
    buildFromTemplate: vi.fn((t: unknown) => ({ template: t })),
    setApplicationMenu: vi.fn(),
  },
  shell: {
    openPath: vi.fn(() => Promise.resolve('')),
    openExternal: vi.fn(() => Promise.resolve('')),
  },
  clipboard: {
    writeText: vi.fn(),
  },
  app: { name: 'Sage' },
}));

vi.mock('electron', () => ({
  Menu: mocks.Menu,
  shell: mocks.shell,
  clipboard: mocks.clipboard,
  app: mocks.app,
}));

let tmpDir: string;
let expectedLogDir: string;

beforeEach(() => {
  vi.resetModules();
  tmpDir = '/tmp/test-logs';
  // logPaths.ts T6 amendment: SAGE_LOG_DIR is the BASE directory; sage files
  // always live under ${SAGE_LOG_DIR}/logs/. Matches logger.ts convention.
  expectedLogDir = join(tmpDir, 'logs');
  process.env.SAGE_LOG_DIR = tmpDir;
  vi.clearAllMocks();
});

describe('buildApplicationMenu', () => {
  it('includes 帮助 menu with 打开日志目录 item', async () => {
    const { buildApplicationMenu } = await import('../menu');
    buildApplicationMenu();

    expect(mocks.Menu.buildFromTemplate).toHaveBeenCalledTimes(1);
    const template = mocks.Menu.buildFromTemplate.mock.calls[0][0] as Array<{
      label?: string;
      submenu?: Array<{ label: string; click?: () => void }>;
    }>;
    const helpMenu = template.find((m) => m.label === '帮助');
    expect(helpMenu).toBeDefined();

    const openItem = helpMenu!.submenu!.find((i) => i.label === '打开日志目录');
    expect(openItem).toBeDefined();
    expect(typeof openItem!.click).toBe('function');

    openItem!.click!();
    expect(mocks.shell.openPath).toHaveBeenCalledWith(expectedLogDir);
  });

  it('includes 复制日志路径 item', async () => {
    const { buildApplicationMenu } = await import('../menu');
    buildApplicationMenu();
    const template = mocks.Menu.buildFromTemplate.mock.calls[0][0] as Array<{
      label?: string;
      submenu?: Array<{ label: string; click?: () => void }>;
    }>;
    const helpMenu = template.find((m) => m.label === '帮助');
    const copyItem = helpMenu!.submenu!.find((i) => i.label === '复制日志路径');

    expect(copyItem).toBeDefined();
    copyItem!.click!();
    expect(mocks.clipboard.writeText).toHaveBeenCalledWith(expectedLogDir);
  });

  it('calls Menu.setApplicationMenu', async () => {
    const { buildApplicationMenu } = await import('../menu');
    buildApplicationMenu();
    expect(mocks.Menu.setApplicationMenu).toHaveBeenCalledTimes(1);
  });
});