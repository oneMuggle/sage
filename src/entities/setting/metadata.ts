/**
 * 设置元数据类型定义
 *
 * 设计文档: docs/superpowers/specs/2026-09-19-settings-governance-design.md
 *
 * 每个设置项都有明确的元数据，用于：
 * - 自动生成搜索索引
 * - 显示生效时机标签
 * - 高级设置折叠
 * - 输入约束验证
 * - 契约测试
 */

/**
 * 设置作用域
 *
 * - global: 全局生效，影响所有会话和 Run
 * - session: 当前会话生效
 * - run: 当前 Run 生效（编排任务）
 * - endpoint: 端点级，影响该端点的所有请求
 * - model: 模型级，影响该模型的所有使用
 */
export type SettingScope = 'global' | 'session' | 'run' | 'endpoint' | 'model';

/**
 * 存储后端
 *
 * - app_settings: 后端 app_settings blob（通过 PUT /api/v1/settings）
 * - preference: 后端 preferences KV（通过 set_preference/get_preference）
 * - electron: Electron 配置文件（通过 IPC）
 * - local: 前端 localStorage
 */
export type StorageBackend = 'app_settings' | 'preference' | 'electron' | 'local';

/**
 * 生效时机
 *
 * - immediate: 立即生效（当前进程重新读取或通过 IPC 更新）
 * - next-request: 下次请求生效
 * - next-run: 下次 Run 生效（当前编排运行不变）
 * - reload-model: 需要重新加载模型
 * - restart: 需要重启应用（Electron 或后端）
 * - save-only: 仅保存，不改变当前运行状态
 */
export type ApplyMode =
  | 'immediate'
  | 'next-request'
  | 'next-run'
  | 'reload-model'
  | 'restart'
  | 'save-only';

/**
 * 可见性级别
 *
 * - basic: 基础设置，所有用户可见
 * - advanced: 高级设置，默认折叠
 * - developer: 开发者专用，需要开启开发者模式
 * - internal: 内部设置，不在设置页显示
 */
export type Visibility = 'basic' | 'advanced' | 'developer' | 'internal';

/**
 * 风险等级
 *
 * - low: 无风险，可随时修改
 * - medium: 可能影响功能，建议了解后再修改
 * - high: 不可逆或需要重启，需谨慎操作
 */
export type RiskLevel = 'low' | 'medium' | 'high';

/**
 * 输入约束类型
 */
export type ConstraintType = 'string' | 'number' | 'boolean' | 'enum' | 'json';

/**
 * 枚举选项
 */
export interface EnumOption {
  value: string;
  label: string;
}

/**
 * 输入约束
 */
export interface SettingConstraints {
  type: ConstraintType;
  min?: number;
  max?: number;
  options?: EnumOption[];
  pattern?: string;
}

/**
 * 设置元数据
 *
 * 描述一个设置项的完整信息，包括：
 * - 基本信息（key、label、description）
 * - 作用域和存储位置
 * - 默认值和约束
 * - 生效时机和风险等级
 * - 依赖关系和验证函数
 */
export interface SettingMetadata {
  /** 设置项唯一标识 */
  key: string;

  /** 中文标签 */
  label: string;

  /** 英文标签（可选） */
  labelEn?: string;

  /** 中文描述 */
  description: string;

  /** 英文描述（可选） */
  descriptionEn?: string;

  /** 作用域 */
  scope: SettingScope;

  /** 存储后端 */
  storage: StorageBackend;

  /** 实际存储 key（与 key 不同时使用） */
  storageKey?: string;

  /** 默认值 */
  defaultValue: unknown;

  /** 生效时机 */
  applyMode: ApplyMode;

  /** 可见性级别 */
  visibility: Visibility;

  /** 风险等级 */
  riskLevel: RiskLevel;

  /** 输入约束 */
  constraints?: SettingConstraints;

  /** 依赖的其他设置 key */
  dependsOn?: string[];

  /** 影响的其他设置 key */
  affects?: string[];

  /**
   * 验证函数
   *
   * @param value 要验证的值
   * @returns 错误信息，或 null 表示验证通过
   */
  validate?: (value: unknown) => string | null;
}

/**
 * 生效时机标签配置
 */
export const APPLY_MODE_LABELS: Record<ApplyMode, { zh: string; en: string; color: string }> = {
  immediate: { zh: '立即生效', en: 'Immediate', color: 'green' },
  'next-request': { zh: '下次请求', en: 'Next Request', color: 'blue' },
  'next-run': { zh: '下次 Run', en: 'Next Run', color: 'blue' },
  'reload-model': { zh: '重新加载模型', en: 'Reload Model', color: 'orange' },
  restart: { zh: '重启生效', en: 'Restart Required', color: 'red' },
  'save-only': { zh: '仅保存', en: 'Save Only', color: 'gray' },
};

/**
 * 风险等级标签配置
 */
export const RISK_LEVEL_LABELS: Record<RiskLevel, { zh: string; en: string; color: string }> = {
  low: { zh: '低风险', en: 'Low Risk', color: 'green' },
  medium: { zh: '中风险', en: 'Medium Risk', color: 'orange' },
  high: { zh: '高风险', en: 'High Risk', color: 'red' },
};
