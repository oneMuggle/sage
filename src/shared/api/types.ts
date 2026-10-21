/**
 * API 类型定义（聚合 barrel）
 *
 * 按领域拆分为 4 个子模块（保持原导出路径向后兼容）：
 * - chatAndEventTypes: Session / Message / AgentEvent / ApiError / ChatConfig
 * - domainEntityTypes: Memory / Knowledge / Skills / Agents / Orchestration
 * - officeDocTypes: Office 文档读写 / 生成 / 归档 / 快照契约
 * - templateAndTaskTypes: Office 差异预览 / 模板 / 日报 / 定时任务 / 演化与进化契约
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
