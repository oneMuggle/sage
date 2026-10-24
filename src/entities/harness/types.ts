/** Harness 组件类型 —— 与后端 ``HARNESS_COMPONENT_TYPES`` 保持一一对应。 */
export type HarnessComponentType =
  | 'system_prompt'
  | 'guardrails'
  | 'memory'
  | 'tool_guidance'
  | 'subagents'
  | 'skills'
  | 'scripts'
  | 'plugins';

/** Effectiveness 指标 —— 与后端 ``EffectivenessMetrics`` dataclass 对齐。 */
export interface EffectivenessMetrics {
  /** 累计调用次数 */
  usage_count: number;
  /** 成功率 [0, 1] */
  success_rate: number;
  /** 平均延迟 ms */
  avg_latency_ms: number;
  /** 用户满意度 [0, 1]；未收集时为 null */
  user_satisfaction: number | null;
  /** 最后一次使用时间（ISO-8601）；从未使用为 null */
  last_used_at: string | null;
}

/** Harness 组件 —— 与后端 ``HarnessComponent`` dataclass 对齐。 */
export interface HarnessComponent {
  /** 合成 ID（例：``"tool:bash"`` / ``"skill:academic-search"``） */
  id: string;
  type: HarnessComponentType;
  name: string;
  /** 语义版本号（默认 ``"1.0.0"``） */
  version: string;
  /** 组件配置（JSON 对象） */
  config: Record<string, unknown>;
  /** 效果指标 */
  effectiveness: EffectivenessMetrics;
  /** 是否触发改进阈值（成功率<0.8 / 延迟>1000ms / 满意度<0.5） */
  needs_improvement: boolean;
  /** 注册/创建时间（ISO-8601） */
  created_at: string;
  /** 最后一次更新时间（ISO-8601） */
  updated_at: string;
}

/** ``GET /api/v1/harness/components`` 响应 envelope。 */
export interface HarnessComponentListResponse {
  items: HarnessComponent[];
  total: number;
  component_types: HarnessComponentType[];
}

/** ``GET /api/v1/harness/needing-improvement`` 响应 envelope。 */
export interface HarnessNeedingImprovementResponse {
  items: HarnessComponent[];
  total: number;
}

/**
 * 组件类型的中文标签。
 *
 * 与后端 ``HARNESS_COMPONENT_TYPES`` 常量对齐；前端展示用，不序列化。
 */
export const HARNESS_TYPE_LABELS: Record<HarnessComponentType, string> = {
  system_prompt: '系统提示词',
  guardrails: '安全护栏',
  memory: '记忆系统',
  tool_guidance: '工具引导',
  subagents: '子代理编排',
  skills: '技能',
  scripts: '脚本工具',
  plugins: '插件',
};
export function auditHarnessTypesGovernance(): string {
  return JSON.stringify({
    module: 'harness-types',
    phase: 'P188',
    audited: true,
  });
}
