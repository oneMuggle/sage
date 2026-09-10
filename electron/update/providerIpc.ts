// electron/update/providerIpc.ts
import type { IpcMain } from 'electron';
import type { ProviderStore } from './providerStore';
import type { UpdateManager } from '../updateManager';
import type { ProviderInstanceConfig } from './providerConfig';

const CHANNELS = [
  'provider:list',
  'provider:get',
  'provider:add',
  'provider:update',
  'provider:remove',
  'provider:set-default',
  'provider:test',
  'update:check-with',
] as const;

export type ProviderChannel = typeof CHANNELS[number];

export function registerProviderIpc(
  ipcMain: IpcMain,
  deps: { providerStore: ProviderStore; updateManager: UpdateManager }
): () => void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handlers: Record<string, (event: unknown, payload: any) => unknown> = {
    'provider:list': async () => {
      const list = await deps.providerStore.list();
      return list.map((c) => maskToken(c));
    },
    'provider:get': async (_e: unknown, { id }: { id: string }): Promise<ProviderInstanceConfig | null> => {
      const cfg = await deps.providerStore.get(id);
      return cfg ? maskToken(cfg) : null;
    },
    'provider:add': async (
      _e: unknown,
      cfg: Omit<ProviderInstanceConfig, 'id' | 'createdAt' | 'updatedAt'>
    ): Promise<{ id: string }> => {
      const id = await deps.providerStore.add(cfg);
      return { id };
    },
    'provider:update': async (
      _e: unknown,
      { id, patch }: { id: string; patch: Partial<ProviderInstanceConfig> }
    ): Promise<{ ok: boolean }> => {
      await deps.providerStore.update(id, patch);
      return { ok: true };
    },
    'provider:remove': async (_e: unknown, { id }: { id: string }): Promise<{ ok: boolean }> => {
      await deps.providerStore.remove(id);
      return { ok: true };
    },
    'provider:set-default': async (_e: unknown, { id }: { id: string }): Promise<{ ok: boolean }> => {
      await deps.providerStore.setDefault(id);
      const mgr = deps.updateManager as unknown as {
        switchProvider?: (id: string) => Promise<void>;
      };
      if (typeof mgr.switchProvider === 'function') {
        await mgr.switchProvider(id);
      }
      return { ok: true };
    },
    'provider:test': async (
      _e: unknown,
      { id }: { id: string }
    ): Promise<{ ok: boolean; latencyMs: number; error?: string }> => {
      const cfg = await deps.providerStore.get(id);
      if (!cfg) return { ok: false, latencyMs: 0, error: 'Provider not found' };
      // 这里直接调用 provider.ping（Phase 1.9 main.ts 注入；Task 1.7 注入也需要补 switchProvider + pingProvider）
      const mgr = deps.updateManager as unknown as {
        pingProvider?: (id: string) => Promise<{ ok: boolean; latencyMs: number; error?: string }>;
      };
      return typeof mgr.pingProvider === 'function'
        ? mgr.pingProvider(id)
        : { ok: false, latencyMs: 0, error: 'pingProvider not implemented' };
    },
    'update:check-with': async (
      _e: unknown,
      { providerId, channel }: { providerId: string; channel: string }
    ): Promise<unknown> => {
      const mgr = deps.updateManager as unknown as {
        checkWithProvider?: (providerId: string, channel: string) => Promise<unknown>;
      };
      return typeof mgr.checkWithProvider === 'function'
        ? mgr.checkWithProvider(providerId, channel)
        : null;
    },
  };

  for (const ch of CHANNELS) {
    ipcMain.handle(ch, handlers[ch]);
  }

  return () => {
    for (const ch of CHANNELS) ipcMain.removeHandler(ch);
  };
}

function maskToken(cfg: ProviderInstanceConfig): ProviderInstanceConfig {
  if ('token' in cfg.config && cfg.config.token) {
    return { ...cfg, config: { ...cfg.config, token: '***masked***' } };
  }
  return cfg;
}