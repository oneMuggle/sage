/**
 * Sage API - Specialist packages (.sage 导入/导出, M1-E) + 内置模板库 (M4-T2)
 *
 * 二进制 zip 不能走通用 `invoke` 通道（`invokeBackend` 总是 `res.json()`），
 * 因此导入/导出走 preload 暴露的 `window.electronAPI.specialists` 桥
 * （主进程 `electron/specialistIpc.ts` 处理原生对话框 + 文件落盘）。
 *
 * 列表/创建/编辑仍用 `agentsApi`，本模块只封装包传输能力 + 模板库。
 */

import type {
  SpecialistPackageExportResult,
  SpecialistPackageImportResult,
} from '../types/electron-api';

import { invoke } from './desktopInvoke';
import type { AgentProfile } from './types/domainEntityTypes';

type SpecialistsBridge = NonNullable<Window['electronAPI']>['specialists'];

/** 模板元数据（不含 system_prompt）。对应后端 list_templates()。 */
export interface SpecialistTemplateMeta {
  id: string;
  name: string;
  tagline: string;
  avatar: string;
  description: string;
  skill_count: number;
}

/** 模板实例化响应。 */
export interface InstantiateTemplateResult {
  id: string;
  name: string;
  template_id: string;
  dropped_bindings: number;
}

/** 版本快照元数据（GET /agents/{id}/versions 单项，M4-T3）。 */
export interface SpecialistVersionMeta {
  version: number;
  reason: 'create' | 'update' | 'rollback';
  /** 毫秒级 Unix 时间戳 */
  created_at: number;
}

/** 字段级 diff（GET /agents/{id}/versions/diff 单项）。 */
export interface SpecialistVersionDiff {
  field: string;
  before: unknown;
  after: unknown;
}

/** 黄金任务检查器（golden_tasks.json 单项，M4-T4）。 */
export interface SpecialistGoldenTaskCheck {
  kind:
    | 'keywords_all'
    | 'keywords_any'
    | 'forbidden'
    | 'refusal'
    | 'regex'
    | 'max_chars';
  value?: string[] | number;
  pattern?: string;
}

/** 黄金任务（GET /specialists/golden-tasks 单项）。 */
export interface SpecialistGoldenTask {
  id: string;
  template_id: string;
  topic: string;
  prompt: string;
  checks: SpecialistGoldenTaskCheck[];
}

/** 黄金任务目录响应。 */
export interface SpecialistGoldenTasksResult {
  tasks: SpecialistGoldenTask[];
  template_ids: string[];
}

/** 单条检查器结果。 */
export interface SpecialistEvalCheckResult {
  check: string;
  passed: boolean;
}

/** 单任务评测结果。 */
export interface SpecialistEvalTaskResult {
  task_id: string;
  template_id: string;
  topic: string;
  passed: boolean;
  checks: SpecialistEvalCheckResult[];
  tokens: number;
  tool_calls: unknown[];
  output_length: number;
  /** runner 异常时的错误信息（此时 passed=false 且 checks 为空）。 */
  error?: string;
}

/** 按模板聚合的通过率。 */
export interface SpecialistEvalTemplateBucket {
  total: number;
  passed: number;
  tokens: number;
  pass_rate: number;
}

/** 评测聚合报告（POST /specialists/{agent_id}/eval 的 report 字段）。 */
export interface SpecialistEvalReport {
  total_tasks: number;
  passed: number;
  failed: number;
  errored: number;
  pass_rate: number;
  total_tokens: number;
  by_template: Record<string, SpecialistEvalTemplateBucket>;
  task_results: SpecialistEvalTaskResult[];
  /** 毫秒级 Unix 时间戳 */
  started_at: number;
  /** 毫秒级 Unix 时间戳 */
  finished_at: number;
}

/** 评测运行响应。 */
export interface SpecialistEvalRunResult {
  run_id: string;
  report: SpecialistEvalReport;
}

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

  /**
   * 返回内置专家模板元数据列表（不含 system_prompt）。
   *
   * @returns 模板数组（按 writing/research/coding/presentation/office 顺序）
   * @throws 桌面端不可用（必须走 Electron IPC）
   */
  async listTemplates(): Promise<SpecialistTemplateMeta[]> {
    const resp = await invoke<{ templates: SpecialistTemplateMeta[] }>(
      'list_specialist_templates',
    );
    return resp?.templates ?? [];
  },

  /**
   * 一键从内置模板创建专家。
   *
   * @returns 新专家的 `{ id, name, template_id, dropped_bindings }`
   * @throws 模板不存在 / 物化失败
   */
  async instantiateTemplate(
    templateId: string,
  ): Promise<InstantiateTemplateResult> {
    return invoke<InstantiateTemplateResult>('instantiate_specialist_template', {
      templateId,
    });
  },

  /**
   * 列出专家的版本快照元数据（version DESC）。
   *
   * @returns `[{ version, reason, created_at }]`；无快照时为空数组
   * @throws 专家不存在（404）
   */
  async listVersions(agentId: string): Promise<SpecialistVersionMeta[]> {
    const resp = await invoke<SpecialistVersionMeta[]>('list_agent_versions', {
      agentId,
    });
    return resp ?? [];
  },

  /**
   * 两个版本之间的字段级 diff（仅后端白名单字段）。
   *
   * @returns `[{ field, before, after }]`；无差异时为空数组
   * @throws 专家不存在 / 任一版本不存在（404）
   */
  async diffVersions(
    agentId: string,
    fromVersion: number,
    toVersion: number,
  ): Promise<SpecialistVersionDiff[]> {
    const resp = await invoke<SpecialistVersionDiff[]>('diff_agent_versions', {
      agentId,
      fromVersion,
      toVersion,
    });
    return resp ?? [];
  },

  /**
   * 回滚专家到指定版本（新版本号 = 当前 + 1，reason=rollback）。
   *
   * @returns 回滚后的完整 profile
   * @throws 专家不存在 / 目标版本不存在（404）
   */
  async rollbackAgent(agentId: string, version: number): Promise<AgentProfile> {
    return invoke<AgentProfile>('rollback_agent', { agentId, version });
  },

  /**
   * 返回黄金任务集目录（M4-T4；任务 + 模板 id 列表）。
   *
   * @throws 数据文件缺失 / schema 非法（500）
   */
  async listGoldenTasks(): Promise<SpecialistGoldenTasksResult> {
    const resp = await invoke<SpecialistGoldenTasksResult>(
      'list_specialist_golden_tasks',
    );
    return { tasks: resp?.tasks ?? [], template_ids: resp?.template_ids ?? [] };
  },

  /**
   * 执行黄金任务集评测（同步等待全部任务跑完，可能耗时较长）。
   *
   * @param agentId 模板实例化的专家 id（specialist-<template>-<6hex>）
   * @param taskIds 指定任务子集；省略 = 跑全部任务
   * @returns `{ run_id, report }`
   * @throws 专家不存在（404）/ 非模板实例化（400）/ 数据文件非法（500）
   */
  async runEval(
    agentId: string,
    taskIds?: string[],
  ): Promise<SpecialistEvalRunResult> {
    return invoke<SpecialistEvalRunResult>('run_specialist_eval', {
      agentId,
      taskIds,
    });
  },
};
