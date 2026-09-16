/**
 * Model Catalog — 前端类型契约 (Task 6, 2026-09-15)
 *
 * 与 backend.model_catalog.schemas 保持字段一一对应:
 * - Decimal 价格保持字符串 (UI 永不计算)
 * - null 表示"未知", 区别于 0
 * - revision / classification 是后端决策结果, 前端只读不写
 */

export interface ModelKey {
  provider: string;
  model_id: string;
}

/** USD per million tokens. 字符串保留精度, 浏览器不参与算术。 */
export interface Price {
  input_per_million: string | null;
  output_per_million: string | null;
  currency: 'USD';
}

export interface CandidateModel {
  model_key: ModelKey;
  /** 模型原生上下文窗口 (tokens); null = 未知 */
  native: number | null;
  /** 服务端报告的窗口, 与 native 可能不同 (例如 Ollama 加载模型大小) */
  service?: number | null;
  price: Price;
  capabilities?: Record<string, boolean> | null;
  architecture?: string | null;
  quantization?: string | null;
  source: string;
  source_updated_at?: string | null;
  pricing_scope: string;
}

export interface CatalogListResponse {
  items: CandidateModel[];
  total: number;
  limit: number;
  offset: number;
}

export interface ContextLimits {
  native: number | null;
  service: number | null;
}

export interface EffectiveModel {
  limits: ContextLimits;
  price: Price;
  /** 每个字段的来源: user_override > service_probe > imported_snapshot > builtin > unknown */
  provenance: Record<string, string>;
  /** 当前 endpoint/model 用户覆盖的 CAS revision。 */
  revision: number;
}

export interface SnapshotMeta {
  id: string;
  source: string;
  digest: string;
  created_at: string;
}

/** 字段级变更明细, 来源 / 旧值 / 新值 / 保护状态 */
export interface SnapshotDiff {
  id: string;
  base_revision: number;
  before: CandidateModel | null;
  after: CandidateModel;
  candidate: CandidateModel;
  clear_fields: string[];
  classification: 'new' | 'updated' | 'conflict' | 'unchanged';
  status: 'pending' | 'applied' | 'ignored';
}

/** 应用层 override patch (PATCH body). */
export interface OverridePatch {
  native?: number | null;
  service?: number | null;
  price?: Price;
  capabilities?: Record<string, boolean> | null;
  architecture?: string | null;
  quantization?: string | null;
}

export interface ProbeData {
  native: number | null;
  service: number | null;
  architecture: string | null;
  quantization: string | null;
}

export interface ProbeResult {
  status: 'success' | 'unsupported' | 'error';
  adapter: string;
  data: ProbeData | null;
  error: string | null;
}

/** 可审核字段白名单 (与 backend.snapshots.FIELDS 对齐) */
export const REVIEWABLE_FIELDS = [
  'native',
  'capabilities',
  'architecture',
  'quantization',
  'price',
] as const;

export type ReviewableField = (typeof REVIEWABLE_FIELDS)[number];

/** 字段展示标签 — 中文 */
export const FIELD_LABELS: Record<ReviewableField, string> = {
  native: '上下文窗口',
  capabilities: '能力',
  architecture: '架构',
  quantization: '量化',
  price: '价格',
};

/** 后端来源标识 — 与 EffectiveModel.provenance.values 对齐 */
export const SOURCE_LABELS: Record<string, string> = {
  user_override: '手动覆盖',
  service_probe: '服务探测',
  imported_snapshot: '导入快照',
  builtin: '内置默认值',
  unknown: '未知',
};
