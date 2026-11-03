/**
 * Sage API - Specialist packages (.sage 导入/导出, M1-E)
 *
 * 二进制 zip 不能走通用 `invoke` 通道（`invokeBackend` 总是 `res.json()`），
 * 因此导入/导出走 preload 暴露的 `window.electronAPI.specialists` 桥
 * （主进程 `electron/specialistIpc.ts` 处理原生对话框 + 文件落盘）。
 *
 * 列表/创建/编辑仍用 `agentsApi`，本模块只封装包传输能力。
 */

import type {
  SpecialistPackageExportResult,
  SpecialistPackageImportResult,
} from '../types/electron-api';

type SpecialistsBridge = NonNullable<Window['electronAPI']>['specialists'];

function getBridge(): SpecialistsBridge | null {
  if (typeof window === 'undefined') return null;
  return window.electronAPI?.specialists ?? null;
}

export const specialistApi = {
  /** 当前运行环境是否支持专家包导入/导出（桌面端才有桥）。 */
  isAvailable(): boolean {
    return getBridge() !== null;
  },

  /**
   * 弹出原生选择器导入 `.sage` 包。
   *
   * @returns 新专家 `{ id, name }`；用户取消选择时返回 null。
   * @throws 桥不可用 / 后端 400（格式非法、注入、密钥、路径穿越等）
   */
  async importPackage(): Promise<SpecialistPackageImportResult | null> {
    const bridge = getBridge();
    if (!bridge) throw new Error('专家包导入仅桌面端可用');
    return bridge.importPackage();
  },

  /**
   * 导出专家包到用户选择的路径（原生另存为对话框）。
   *
   * @returns `{ ok: true, path }`；用户取消时返回 null。
   * @throws 桥不可用 / agentId 非法 / 后端 404
   */
  async exportPackage(agentId: string): Promise<SpecialistPackageExportResult | null> {
    const bridge = getBridge();
    if (!bridge) throw new Error('专家包导出仅桌面端可用');
    return bridge.exportPackage(agentId);
  },
};
