/**
 * electron/petIpc.ts — P2 宠物包导入的 IPC 接线。
 *
 * 通道（渲染端桥声明见 src/shared/types/electron-api.d.ts `pet`）：
 *   pet:list-imports   → 已导入宠物包（含内联 data URL 的 CSS）
 *   pet:import-plan    → 原生选 zip → 校验/隔离，返回 plan（取消 = null）
 *   pet:import-commit  → 渲染端确认（含覆盖授权）后移入 userData/pets
 *   pet:import-discard → 放弃本次导入，清理隔离区
 *   pet:remove-pack    → 删除已导入宠物包
 *
 * 逻辑全在 petImport.ts（纯文件系统，可脱离 Electron 单测）；本模块只做
 * dialog / 路径解析 / 活跃 token 记账。
 */
import { BrowserWindow, dialog } from 'electron';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

import type { RegisterIpcHandler } from './officeIpc';
import {
  commitImport,
  discardImport,
  listInstalledPacks,
  planImportFromZip,
  removePack,
  sweepStaleQuarantine,
  type PetImportEnv,
} from './petImport';
import { resolveSageUserDataDir } from './userDataPaths';

const MAX_ZIP_BYTES = 8 * 1024 * 1024;

/** 已 plan 未 commit 的 token —— 隔离区清扫时保护，防误删确认中的包。 */
const pendingTokens = new Set<string>();

export function resolvePetEnv(): PetImportEnv {
  const base = resolveSageUserDataDir();
  return { petsDir: join(base, 'pets'), quarantineDir: join(base, 'pet-quarantine') };
}

function focusedWindow(): BrowserWindow | undefined {
  return BrowserWindow.getFocusedWindow() ?? undefined;
}

export function registerPetIpc(register: RegisterIpcHandler): void {
  register('pet:list-imports', (async () => {
    return listInstalledPacks(resolvePetEnv());
  }) as (...args: unknown[]) => unknown);

  register(
    'pet:import-plan',
    (async (): Promise<unknown> => {
      const env = resolvePetEnv();
      await sweepStaleQuarantine(env, pendingTokens).catch(() => undefined);
      const picked = await dialog.showOpenDialog(focusedWindow()!, {
        title: '选择宠物包（zip）',
        properties: ['openFile'],
        filters: [{ name: 'Pet pack', extensions: ['zip'] }],
      });
      if (picked.canceled || picked.filePaths.length === 0) return null;
      const source = picked.filePaths[0]!;
      const bytes = await readFile(source);
      if (bytes.length > MAX_ZIP_BYTES)
        return { ok: false, errors: [`zip 超过 ${MAX_ZIP_BYTES} 字节上限`] };
      const plan = await planImportFromZip(bytes, env);
      if (plan.ok) pendingTokens.add(plan.token);
      return plan;
    }) as (...args: unknown[]) => unknown,
  );

  register(
    'pet:import-commit',
    (async (_event: unknown, opts: { token: string; overwrite: boolean }) => {
      const result = await commitImport(opts.token, { overwrite: !!opts.overwrite }, resolvePetEnv());
      pendingTokens.delete(opts.token);
      return result;
    }) as (...args: unknown[]) => unknown,
  );

  register(
    'pet:import-discard',
    (async (_event: unknown, opts: { token: string }) => {
      const result = await discardImport(opts.token, resolvePetEnv());
      pendingTokens.delete(opts.token);
      return result;
    }) as (...args: unknown[]) => unknown,
  );

  register(
    'pet:remove-pack',
    (async (_event: unknown, opts: { id: string }) => {
      return removePack(opts.id, resolvePetEnv());
    }) as (...args: unknown[]) => unknown,
  );
}

/** 测试后门：重置跨用例泄漏的 token 记账。 */
export function __resetPendingTokensForTests(): void {
  pendingTokens.clear();
}
