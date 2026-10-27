/**
 * API 类型定义（聚合 barrel）
 *
 * 按领域拆分为 4 个子模块（保持原导出路径向后兼容）：
 * - chatAndEventTypes: Session / Message / AgentEvent / ApiError / ChatConfig
 * - domainEntityTypes: Memory / Knowledge / Skills / Agents / Orchestration
 * - officeDocTypes: Office 文档读写 / 生成 / 归档 / 快照契约
 * - templateAndTaskTypes: Office 差异预览 / 模板 / 日报 / 定时任务 / 演化与进化契约
 *
 * 布局裁决（2026-10-27，见 docs/mcp-win7-converge-src-types-adr-20261027.md）：
 * main 侧把 office 契约内联在本文件（单文件已 753 行，逼近 architecture-policy
 * maxFileLines=800），win7 侧拆成 types/officeDocTypes.ts。本分支**保留拆分**：
 *   1) 单文件合并会超 800 行上限；
 *   2) main 的子模块经 `from '../types'` 反向取 office 类型，形成 types.ts ↔
 *      types/* 的类型导入环，拆分后子模块直接 `./officeDocTypes`，依赖为 DAG。
 * 因此与 main 合并时，**按符号而非按文件**搬运：main `types.ts` 里的 office 段
 * 一律落到本目录的 `types/officeDocTypes.ts`，其余段落到同名子模块。
 */
export * from './types/chatAndEventTypes';
export * from './types/domainEntityTypes';
export * from './types/officeDocTypes';
export * from './types/templateAndTaskTypes';
export function formatTaskPlanItemSummary(item: {
  task_id: string;
  agent_id: string;
  goal: string;
  parent_task_id?: string | null;
  depth?: number;
}): string {
  return `${item.task_id} · agent=${item.agent_id} · parent=${item.parent_task_id ?? 'root'} · depth=${item.depth ?? 0}`;
}

export function formatTaskPlanItemJson(item: {
  task_id: string;
  agent_id: string;
  goal: string;
  parent_task_id?: string | null;
  depth?: number;
}): string {
  return JSON.stringify(
    {
      taskId: item.task_id,
      agentId: item.agent_id,
      goal: item.goal,
      parentTaskId: item.parent_task_id ?? null,
      depth: item.depth ?? 0,
    },
    null,
    2,
  );
}
export function auditSharedApiTypesGovernance(): string {
  return JSON.stringify({
    module: 'shared-api-types',
    phase: 'P189',
    audited: true,
  });
}
