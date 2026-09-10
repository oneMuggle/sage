// electron/update/providerIpc.ts
import type { IpcMain } from 'electron';
import type { ProviderStore } from './providerStore';
import type { UpdateManager } from './updateManager';

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
  const handlers: Record<string, (event: any, payload: any) => any> = {
    'provider:list': async () => {
      const list = await deps.providerStore.list();
      return list.map((c) => maskToken(c));
    },
    'provider:get': async (_e, { id }) => {
      const cfg = await deps.providerStore.get(id);
      return cfg ? maskToken(cfg) : null;
    },
    'provider:add': async (_e, cfg) => {
      const id = await deps.providerStore.add(cfg);
      return { id };
    },
    'provider:update': async (_e, { id, patch }) => {
      await deps.providerStore.update(id, patch);
      return { ok: true };
    },
    'provider:remove': async (_e, { id }) => {
      await deps.providerStore.remove(id);
      return { ok: true };
    },
    'provider:set-default': async (_e, { id }) => {
      await deps.providerStore.setDefault(id);
      if (typeof (deps.updateManager as any).switchProvider === 'function') {
        await (deps.updateManager as any).switchProvider(id);
      }
      return { ok: true };
    },
    'provider:test': async (_e, { id }) => {
      const cfg = await deps.providerStore.get(id);
      if (!cfg) return { ok: false, latencyMs: 0, error: 'Provider not found' };
      // 这里直接调用 provider.ping（Phase 1.9 main.ts 注入；Task 1.7 注入也需要补 switchProvider + pingProvider）
      const mgr = deps.updateManager as any;
      return typeof mgr.pingProvider === 'function'
        ? mgr.pingProvider(id)
        : { ok: false, latencyMs: 0, error: 'pingProvider not implemented' };
    },
    'update:check-with': async (_e, { providerId, channel }) => {
      const mgr = deps.updateManager as any;
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

function maskToken(cfg: any): any {
  if (cfg.config?.token) {
    return { ...cfg, config: { ...cfg.config, token: '***masked***' } };
  }
  return cfg;
}