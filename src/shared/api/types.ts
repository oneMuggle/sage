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
