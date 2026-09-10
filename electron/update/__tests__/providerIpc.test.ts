import { describe, it, expect } from 'vitest';
import { registerProviderIpc } from '../../../electron/update/providerIpc';

describe('providerIpc', () => {
  it('registers all 8 channels', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const handlers: Record<string, any> = {};
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ipcMain = { handle: (ch: string, h: any) => { handlers[ch] = h; } };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    registerProviderIpc(ipcMain as any, { providerStore: {} as any, updateManager: {} as any });
    expect(handlers['provider:list']).toBeDefined();
    expect(handlers['provider:get']).toBeDefined();
    expect(handlers['provider:add']).toBeDefined();
    expect(handlers['provider:update']).toBeDefined();
    expect(handlers['provider:remove']).toBeDefined();
    expect(handlers['provider:set-default']).toBeDefined();
    expect(handlers['provider:test']).toBeDefined();
    expect(handlers['update:check-with']).toBeDefined();
  });
});