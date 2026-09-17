/**
 * sage-file:// 协议注册 — P9/P13 (UI 优化循环, 2026-09-14)。
 *
 * Electron 21 的 protocol.handle 尚未引入，使用 registerFileProtocol
 * （Electron 22-28 仍可用，win7 线同版本 cherry-pick 安全）。
 * 校验逻辑全部在 ./sageFileUrl（纯函数，可单测）；本模块维护工作区
 * 注册表并做薄注册。
 *
 * P13 收紧：注册表由 main 进程维护，渲染端 SessionWorkspaceProvider
 * 绑定工作区时经 sage-file:register-root IPC 登记。未注册根的文件
 * 一律拒绝（fail-closed），不再信任渲染端 URL 中的 ?ws= 自声明。
 *
 * P22 allowed_paths 扩展 (2026-09-17)：项目级额外允许访问的路径规则
 * 由渲染端 `projectApi.updateAllowedPaths()` 成功后调用
 * `registerAllowedPaths()` 登记；与工作区根 OR-组合：任一命中即放行。
 */
import { realpathSync } from 'node:fs';

import { resolveSageFileUrl } from './sageFileUrl';
import { logger } from './logger';

/** 已注册的工作区根（realpath 归一）。 */
const workspaceRoots = new Set<string>();

/**
 * 项目级 allowed_paths 注册表 (P22, 2026-09-17):
 *   projectId → 规则字符串数组（与后端 ProjectSummary.allowedPaths 一致）。
 *
 * 协议层不做后端那种 glob 展开，仅透传给 ``resolveSageFileUrl``。
 * 渲染端在 ``projectApi.updateAllowedPaths`` / `register()` 成功后调用
 * ``registerAllowedPaths()`` 同步；后端是事实源（API 校验、模式匹配），
 * 主进程只做"已批准规则"的内存缓存，加速协议层校验。
 */
const allowedPathsByProject = new Map<string, ReadonlyArray<string>>();

/**
 * 登记允许 sage-file:// 读取的工作区根。
 * realpath 归一（符号链接/大小写吸收），登记幂等。
 * 返回 true 表示登记成功；false 表示路径无效或不存在。
 */
export function registerWorkspaceRoot(root: string): boolean {
  try {
    const real = realpathSync.native(root);
    workspaceRoots.add(real);
    return true;
  } catch {
    return false;
  }
}

/**
 * P17: 注销工作区根 —— 会话解绑/切换工作区时调用，移除不再需要的根。
 * 防止旧工作区路径永久残留在白名单中（最小权限原则）。
 * 返回 true 表示确实移除了一个根；false 表示该根不存在。
 */
export function unregisterWorkspaceRoot(root: string): boolean {
  try {
    const real = realpathSync.native(root);
    return workspaceRoots.delete(real);
  } catch {
    return false;
  }
}

/**
 * P22 (2026-09-17): 登记项目级 allowed_paths 规则。
 *
 * 规则语义与后端 ``backend/office/allowed_paths.py::is_allowed`` 保持一致
 * （`~` 展开、`*` 单层、`**` 任意子层）；主进程仅做"已批准列表"缓存。
 *
 * 注册幂等；传入空数组视为"取消项目级扩展"，允许在 UI 端清空规则后
 * 撤回登记而不必显式调用 ``unregisterAllowedPaths``。
 */
export function registerAllowedPaths(projectId: string, paths: ReadonlyArray<string>): void {
  allowedPathsByProject.set(projectId, [...paths]);
}

/** P22: 注销项目级 allowed_paths（项目被删除/移除时调用）。 */
export function unregisterAllowedPaths(projectId: string): boolean {
  return allowedPathsByProject.delete(projectId);
}

/** 获取当前注册表快照（测试/诊断用）。 */
export function getRegisteredRoots(): ReadonlySet<string> {
  return workspaceRoots;
}

/** P22: 获取项目级 allowed_paths 快照（测试用）。 */
export function getAllowedPathsByProject(): ReadonlyMap<string, ReadonlyArray<string>> {
  return allowedPathsByProject;
}

export function registerSageFileProtocol(): void {
  // 动态引入 electron：本模块被 main.ts 静态导入，而若干 electron 单测
  // 会以部分 mock 替换 'electron' —— 顶层静态引入会让这些测试在收集期
  // 因 mock 缺 protocol 导出而报未处理错误。
  void (async () => {
    const { protocol } = await import('electron');
    protocol.registerFileProtocol('sage-file', (request, callback) => {
      const allowedLists = Array.from(allowedPathsByProject.values());
      const resolved = resolveSageFileUrl(request.url, workspaceRoots, allowedLists);
      if (resolved.ok) {
        callback({ path: resolved.path });
      } else {
        logger.warn('sage-file: rejected', { url: request.url, reason: resolved.reason });
        callback({ error: -3 }); // net::ERR_ABORTED
      }
    });
  })().catch((err: unknown) => {
    logger.warn('sage-file: register failed', { error: String(err) });
  });
}
