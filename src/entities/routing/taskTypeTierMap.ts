// src/entities/routing/taskTypeTierMap.ts
//
// Task 11 (2026-10-28) 智能路由：设置页只读展示用的任务类型 → 分档映射。
//
// 映射的**源在服务端**（`backend/routing/routing_engine.py` 的
// `TASK_TYPE_TO_TIER`）。这里只是给「设置 → 模型选择」页展示只读表的副本；
// `taskTypeTierMap.test.ts` 会直接读 Python 源码比对，漂移即红。
//
// 中文标签与 `src/widgets/chat/SessionModelPicker.tsx` 里的同名字符串一致
// （Task 7 在那边留了一份未导出的局部副本，后续可合并到本模块）。

import type { RoutingTaskType } from './taskType';
import type { Tier } from './types';

/** 与 backend/routing/routing_engine.py 的 TASK_TYPE_TO_TIER 一一对应。 */
export const TASK_TYPE_TIER_MAP: Record<RoutingTaskType, Tier> = {
  simple_chat: 'fast',
  chat: 'fast',
  code_generation: 'balanced',
  code_review: 'powerful',
  analysis: 'powerful',
  writing: 'balanced',
  translation: 'fast',
  summarization: 'balanced',
  vision_task: 'balanced',
};

export const TIER_LABELS: Record<Tier, string> = {
  fast: '快速',
  balanced: '均衡',
  powerful: '强力',
};

export const TASK_TYPE_LABELS: Record<RoutingTaskType, string> = {
  chat: '聊天',
  simple_chat: '简单问答',
  code_generation: '代码生成',
  code_review: '代码审查',
  analysis: '深度分析',
  writing: '写作',
  translation: '翻译',
  summarization: '摘要',
  vision_task: '图像理解',
};
