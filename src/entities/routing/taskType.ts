// src/entities/routing/taskType.ts
//
// Task 7 (2026-10-28) 智能路由：任务类型枚举与持久化。
//
// 与后端 backend/routing/routing_engine.py 的 TASK_TYPE_TO_TIER 键集一一对应。
// 前端只做「选择 + 记忆」，不复刻 tier 映射 —— 映射属于服务端决策，
// routeModel 的响应已带回 selected_model.tier 与 reason，重复实现只会漂移。
//
// 本模块可在无 UI 上下文里被 useChat import（不含任何显示名 / JSX）。

/** 与后端 TASK_TYPE_TO_TIER 的键集一一对应；新增键必须两边同时改。 */
export type RoutingTaskType =
  | 'simple_chat'
  | 'chat'
  | 'code_generation'
  | 'code_review'
  | 'analysis'
  | 'writing'
  | 'translation'
  | 'summarization'
  | 'vision_task';

/** 顺序即 UI 下拉顺序：先最常用，再其余。 */
export const ROUTING_TASK_TYPES: readonly RoutingTaskType[] = [
  'chat',
  'simple_chat',
  'code_generation',
  'code_review',
  'analysis',
  'writing',
  'translation',
  'summarization',
  'vision_task',
] as const;

/** 缺省任务类型；与后端 apply_auto_routing_overlay 的 `task_type or "chat"` 一致。 */
export const DEFAULT_ROUTING_TASK_TYPE: RoutingTaskType = 'chat';

export const ROUTING_TASK_TYPE_STORAGE_KEY = 'routingTaskType';

function isRoutingTaskType(value: string | null): value is RoutingTaskType {
  return value !== null && (ROUTING_TASK_TYPES as readonly string[]).includes(value);
}

/**
 * 读取持久化的任务类型。
 *
 * 非法 / 缺失 / 存储抛错（jsdom、隐私模式）一律回退默认值 —— 与
 * `src/pages/Welcome.tsx` 的 `welcomeModelId` 先例同风格，但不吞掉合法值。
 */
export function getRoutingTaskType(): RoutingTaskType {
  try {
    const stored = localStorage.getItem(ROUTING_TASK_TYPE_STORAGE_KEY);
    return isRoutingTaskType(stored) ? stored : DEFAULT_ROUTING_TASK_TYPE;
  } catch {
    return DEFAULT_ROUTING_TASK_TYPE;
  }
}

/** 持久化任务类型；忽略存储异常（配额 / 隐私模式不影响当次会话）。 */
export function setRoutingTaskType(taskType: RoutingTaskType): void {
  try {
    localStorage.setItem(ROUTING_TASK_TYPE_STORAGE_KEY, taskType);
  } catch {
    // 存储不可用不是致命错误：当次会话仍按内存中的选择路由。
  }
}
