/**
 * 项目模块 API 客户端 (P1, 2026-09-13)。
 *
 * "项目" = 用户在侧边栏登记的工作目录（对标 Cursor Recent Workspaces）。
 * 后端契约见 backend/api/project_routes.py；会话归属复用会话工作区绑定。
 *
 * M3 项目上下文沉淀 (2026-09-15):
 * - ProjectSummary 透出 description/instructions, 供侧边栏概览面板就地编辑
 * - ProjectMaterial 类型 + 资料 CRUD + save-answer(把可见回答固化进项目)
 *
 * 2026-09-17 allowed_paths 扩展：
 * - 项目可配置额外允许访问的路径规则列表（project.allowed_paths）
 * - 支持 .gitignore 风格通配符（`~/Documents/**`、`/tmp/scratch/*`）
 * - 读取遵守 allowed_paths，写入仍限于 workspace 内（读写非对称）
 */

import type { Session } from './types';

/** 项目清单条目（camelCase，渲染端消费） */
export interface ProjectSummary {
  id: string;
  /** 规范化绝对路径（与 session_workspace_bindings.workspace_path 同口径） */
  path: string;
  /** 目录 basename，会话标题与行展示用 */
  name: string;
  createdAt: number;
  lastOpenedAt: number;
  /** 归属该项目的未归档会话数（活跃绑定聚合） */
  sessionCount: number;
  /** 最近活跃会话 id；无绑定会话时为 null */
  lastSessionId: string | null;
  /** M3: 项目描述 (PATCH /projects/{id})。后端 None 表示未设置 */
  description?: string | null;
  /** M3: 项目指令 (system prompt 注入, 优先级高于全局风格偏好) */
  instructions?: string | null;
  /**
   * 额外允许访问的路径规则列表。
   * 类 .gitignore 语法（`~/Documents/**`、`/tmp/*` 等）。
   * 默认 []，表示不扩展访问范围。
   */
  allowedPaths: string[];
  /** 项目类型分类 (2026-09-24) */
  projectType?: ProjectType | null;
  /** 项目阶段 */
  projectStage?: string | null;
  /** 版本控制模式: 'git' | 'builtin' | 'svn' */
  vcsMode?: string;
  /** 自动检测的项目类型 */
  detectedType?: ProjectType | null;
}

/** 项目类型枚举 */
export type ProjectType = 'coding' | 'research' | 'business' | 'personal';

/** 项目约束实体 (2026-09-24) */
export interface ProjectConstraint {
  id: string;
  projectId: string;
  /** 约束类别 */
  category: string;
  /** 约束内容（自然语言） */
  content: string;
  /** 触发条件（glob 模式或 'always'） */
  triggerPattern?: string | null;
  /** 优先级 1-10，高优先级覆盖低优先级 */
  priority: number;
  /** 是否启用 */
  enabled: boolean;
  createdAt: number;
  updatedAt: number;
}

/** 创建约束请求 */
export interface CreateConstraintPayload {
  category: string;
  content: string;
  triggerPattern?: string;
  priority?: number;
}

/** 更新约束请求 */
export interface UpdateConstraintPayload {
  category?: string;
  content?: string;
  triggerPattern?: string;
  priority?: number;
  enabled?: boolean;
}

/** 项目里程碑实体 (2026-09-24) */
export interface ProjectMilestone {
  id: string;
  projectId: string;
  title: string;
  description?: string | null;
  /** 所属阶段 */
  stage?: string | null;
  /** 截止日期 */
  dueDate?: string | null;
  /** 完成时间 */
  completedAt?: number | null;
  /** 状态: pending | in_progress | completed | blocked */
  status: string;
  /** 排序顺序 */
  sortOrder: number;
  createdAt: number;
}

/** 创建里程碑请求 */
export interface CreateMilestonePayload {
  title: string;
  description?: string;
  stage?: string;
  dueDate?: string;
  status?: string;
  sortOrder?: number;
}

/** 更新里程碑请求 */
export interface UpdateMilestonePayload {
  title?: string;
  description?: string;
  stage?: string;
  dueDate?: string;
  completedAt?: number;
  status?: string;
  sortOrder?: number;
}

/** AI 任务分解：预览里程碑节点（可嵌套） */
export interface PreviewMilestoneNode {
  title: string;
  description?: string | null;
  stage?: string | null;
  dueDate?: string | null;
  estimatedDays?: number | null;
  children: PreviewMilestoneNode[];
}

/** AI 任务分解：预览响应 */
export interface DecomposePreviewResult {
  reasoning: string;
  milestones: PreviewMilestoneNode[];
  totalCount: number;
}

/** AI 任务分解：预览请求参数 */
export interface DecomposePreviewPayload {
  requirement: string;
  context?: string;
}

/** AI 任务分解：应用请求参数 */
export interface DecomposeApplyPayload {
  milestones: PreviewMilestoneNode[];
}

/** AI 任务分解：应用响应 */
export interface DecomposeApplyResult {
  createdCount: number;
  milestoneIds: string[];
}

/** 项目类型检测结果 */
export interface ProjectTypeDetectionResult {
  detectedType: ProjectType;
  confidence: number;
  signals: string[];
  /** L2 子类型 key，null 表示仅识别到 L1 */
  subType: string | null;
  /** 技术栈标记（package.json / pyproject.toml 等解析结果） */
  techStack: string[];
}

/** POST /projects/{id}/open 响应：复用最近会话时 created=false */
export interface ProjectOpenResult {
  project: ProjectSummary;
  session: Session;
  created: boolean;
}

/**
 * M3: 资料当前状态——ready 进入 system prompt, pending_index/failed 被排除。
 * 后端 add() 默认直接写 ready（添加即生效）; pending_index/failed 预留给
 * 未来的异步索引管线, 当前生产路径不会产生。
 */
export type ProjectMaterialStatus = 'pending_index' | 'ready' | 'failed';

/** M3: 项目资料实体。content 可能很大, UI 默认折叠/截断展示。 */
export interface ProjectMaterial {
  id: string;
  projectId: string;
  /** 来源消息 id（直接 addMaterial 时为 null） */
  sourceMessageId: string | null;
  /** SHA-256 hex, 用于去重 (project_id, content_hash) UNIQUE INDEX */
  contentHash: string;
  content: string;
  status: ProjectMaterialStatus;
  /** 预留: 异步索引落地的 wiki 相对路径; 当前恒为 null */
  wikiPagePath: string | null;
  errorMessage: string | null;
  createdAt: number;
  /** NotebookLM 式资料源受控开关：false 时保留资料但暂停注入 system prompt */
  enabled?: boolean;
}

/** PATCH /projects/{id} 请求体：只传要改的字段, 后端 model_fields_set 语义保留未改字段 */
export interface ProjectUpdatePatch {
  description?: string | null;
  instructions?: string | null;
  project_type?: ProjectType | null;
  project_stage?: string | null;
  vcs_mode?: 'git' | 'builtin' | 'none' | null;
}

export interface ProjectScaffoldOptions {
  projectType?: ProjectType;
  createDirectories?: boolean;
  createSageMd?: boolean;
  importDefaultConstraints?: boolean;
  seedDefaultMilestones?: boolean;
}

export interface ProjectContextBudget {
  projectId: string;
  l1ConventionsChars: number;
  l2MetadataChars: number;
  l2ConstraintsChars: number;
  l3ProfileChars: number;
  l4MaterialsChars: number;
  totalChars: number;
  capChars: number;
  perFileCapChars: number;
  usageRatio: number;
  activeMaterialsCount: number;
  totalMaterialsCount: number;
  enabledConstraintsCount: number;
  synthesizedPreview?: string;
}

export interface WorkspaceArtifactItem {
  name: string;
  relativePath: string;
  ext: string;
  category: string;
  sizeBytes: number;
  modifiedAt: number;
}

export interface WorkspaceDirectorySummary {
  name: string;
  fileCount: number;
}

export interface WorkspaceCheckpointItem {
  id: string;
  label: string;
  createdAt: number;
  fileCount: number;
}

export interface RestoreCheckpointResult {
  id: string;
  label: string;
  restoredFiles: string[];
  restoredAt: number;
}

export interface ProjectWorkspaceOverview {
  projectId: string;
  hasSageMd: boolean;
  hasHooksJson: boolean;
  checkpointCount?: number;
  latestCheckpointAt?: number | null;
  recentCheckpoints?: WorkspaceCheckpointItem[];
  codingIndicators: string[];
  officeDeliverables: WorkspaceArtifactItem[];
  researchArtifacts: WorkspaceArtifactItem[];
  directorySummary: WorkspaceDirectorySummary[];
}

export interface ProjectScaffoldResult {
  project: ProjectSummary;
  createdDirectories: string[];
  createdFiles: string[];
  importedConstraintsCount: number;
  seededMilestonesCount: number;
  recommendedTemplates: string[];
}

export interface ProjectWire {
  id: string;
  path: string;
  name: string;
  created_at: number;
  last_opened_at: number;
  description?: string | null;
  instructions?: string | null;
  session_count?: number;
  last_session_id?: string | null;
  allowed_paths?: string[];
  // Project type classification (2026-09-24)
  project_type?: string | null;
  project_stage?: string | null;
  vcs_mode?: string;
  detected_type?: string | null;
}

export interface ProjectListWire {
  projects: ProjectWire[];
}

export interface ProjectOpenWire {
  project: ProjectWire;
  session: Session;
  created: boolean;
}

export interface ProjectSessionsWire {
  sessions: Session[];
}

export interface ProjectMaterialWire {
  id: string;
  project_id: string;
  source_message_id: string | null;
  content_hash: string;
  content: string;
  status: ProjectMaterialStatus;
  wiki_page_path: string | null;
  error_message: string | null;
  created_at: number;
  enabled?: boolean;
}

export interface ProjectMaterialsListWire {
  materials: ProjectMaterialWire[];
}

export interface ProjectAllowedPathsWire {
  id: string;
  allowed_paths: string[];
}

export function mapProject(p: ProjectWire): ProjectSummary {
  return {
    id: p.id,
    path: p.path,
    name: p.name,
    createdAt: p.created_at,
    lastOpenedAt: p.last_opened_at,
    description: p.description ?? null,
    instructions: p.instructions ?? null,
    sessionCount: p.session_count ?? 0,
    lastSessionId: p.last_session_id ?? null,
    allowedPaths: p.allowed_paths ?? [],
    // Project type classification (2026-09-24)
    projectType: (p.project_type as ProjectType) ?? null,
    projectStage: p.project_stage ?? null,
    vcsMode: p.vcs_mode ?? 'builtin',
    detectedType: (p.detected_type as ProjectType) ?? null,
  };
}

/**
 * P22 (2026-09-17): 把项目的 allowed_paths 同步到主进程 sage-file://
 * 协议注册表。失败不抛（best-effort，仅日志），避免 IPC 异常阻断
 * 项目 API 主流程；渲染端可继续工作，只是图片渲染可能受限。
 */
export async function syncAllowedPathsToMain(
  projectId: string,
  paths: ReadonlyArray<string>,
): Promise<void> {
  const api = typeof window !== 'undefined' ? window.electronAPI?.sageFile : undefined;
  if (!api) return;
  try {
    await api.registerAllowedPaths(projectId, [...paths]);
  } catch (err) {
    console.warn('[projectApi] sync allowed_paths to main failed', { projectId, err });
  }
}

/** P22: 从主进程 sage-file 注册表中注销项目级 allowed_paths。 */
export async function unregisterAllowedPathsFromMain(projectId: string): Promise<void> {
  const api = typeof window !== 'undefined' ? window.electronAPI?.sageFile : undefined;
  if (!api) return;
  try {
    await api.unregisterAllowedPaths(projectId);
  } catch (err) {
    console.warn('[projectApi] unregister allowed_paths from main failed', { projectId, err });
  }
}

export function mapMaterial(m: ProjectMaterialWire): ProjectMaterial {
  return {
    id: m.id,
    projectId: m.project_id,
    sourceMessageId: m.source_message_id,
    contentHash: m.content_hash,
    content: m.content,
    status: m.status,
    wikiPagePath: m.wiki_page_path,
    errorMessage: m.error_message,
    createdAt: m.created_at,
    enabled: m.enabled ?? true,
  };
}

export interface ProjectDiagnoseResult {
  projectId: string;
  level: 'satisfied' | 'partial' | 'unsatisfied' | string;
  detectedLanguages: string[];
  availableRuntimes: string[];
  testCommands: string[];
  hooksConfigExists: boolean;
  hooksCount: number;
  hooksTrusted: boolean;
  recommendations: string[];
}

export interface ProjectCharter {
  projectId: string;
  exists: boolean;
  content: string;
  charCount: number;
  recommendedTemplate: string;
}

export interface WorkspaceCheckpointDetail {
  id: string;
  label: string;
  createdAt: number;
  fileCount: number;
  files: string[];
  snapshots: Record<string, string>;
}

export interface ConstraintWire {
  id: string;
  project_id: string;
  category: string;
  content: string;
  trigger_pattern?: string | null;
  priority: number;
  enabled: boolean;
  created_at: number;
  updated_at: number;
}

export interface MilestoneWire {
  id: string;
  project_id: string;
  title: string;
  description?: string | null;
  stage?: string | null;
  due_date?: string | null;
  completed_at?: number | null;
  status: string;
  sort_order: number;
  created_at: number;
}

/** AI 任务分解：预览里程碑节点（snake_case wire 格式） */
export interface PreviewMilestoneNodeWire {
  title: string;
  description?: string | null;
  stage?: string | null;
  due_date?: string | null;
  estimated_days?: number | null;
  children: PreviewMilestoneNodeWire[];
}

/** AI 任务分解：预览响应（wire 格式） */
export interface DecomposePreviewWire {
  reasoning: string;
  milestones: PreviewMilestoneNodeWire[];
  total_count: number;
}

/** AI 任务分解：应用响应（wire 格式） */
export interface DecomposeApplyWire {
  created_count: number;
  milestone_ids: string[];
}

export interface ProjectTypeDetectWire {
  project_type: string | null;
  confidence: number;
  signals: Array<{ type: string; weight: number }>;
  sub_type?: string | null;
  tech_stack?: string[];
}

export function mapConstraint(c: ConstraintWire): ProjectConstraint {
  return {
    id: c.id,
    projectId: c.project_id,
    category: c.category,
    content: c.content,
    triggerPattern: c.trigger_pattern ?? null,
    priority: c.priority,
    enabled: c.enabled,
    createdAt: c.created_at,
    updatedAt: c.updated_at,
  };
}

export function mapMilestone(m: MilestoneWire): ProjectMilestone {
  return {
    id: m.id,
    projectId: m.project_id,
    title: m.title,
    description: m.description ?? null,
    stage: m.stage ?? null,
    dueDate: m.due_date ?? null,
    completedAt: m.completed_at ?? null,
    status: m.status,
    sortOrder: m.sort_order,
    createdAt: m.created_at,
  };
}

/** 递归映射预览里程碑节点（wire → camelCase） */
export function mapPreviewMilestoneNode(w: PreviewMilestoneNodeWire): PreviewMilestoneNode {
  return {
    title: w.title,
    description: w.description ?? null,
    stage: w.stage ?? null,
    dueDate: w.due_date ?? null,
    estimatedDays: w.estimated_days ?? null,
    children: w.children.map(mapPreviewMilestoneNode),
  };
}

/** 映射 AI 任务分解预览响应 */
export function mapDecomposePreview(w: DecomposePreviewWire): DecomposePreviewResult {
  return {
    reasoning: w.reasoning,
    milestones: w.milestones.map(mapPreviewMilestoneNode),
    totalCount: w.total_count,
  };
}

/** 映射 AI 任务分解应用响应 */
export function mapDecomposeApply(w: DecomposeApplyWire): DecomposeApplyResult {
  return {
    createdCount: w.created_count,
    milestoneIds: w.milestone_ids,
  };
}

// ── M2: 对话知识沉淀 (2026-10-12) ───────────────────────────────────────────

/** M2: LLM 建议的知识条目（camelCase，渲染端消费） */
export interface KnowledgeEntryProposal {
  content: string;
  category: string;
  importance: number;
  sourceMessageIds: string[];
  reasoning?: string | null;
}

/** M2: 知识提取预览响应 */
export interface ExtractKnowledgeResult {
  reasoning: string;
  entries: KnowledgeEntryProposal[];
  projectKey: string;
}

/** M2: 知识提取请求参数 */
export interface ExtractKnowledgePayload {
  sessionId: string;
  maxMessages?: number;
}

/** M2: 知识确认请求参数 */
export interface ConfirmKnowledgePayload {
  entries: KnowledgeEntryProposal[];
}

/** M2: 知识确认响应 */
export interface ConfirmKnowledgeResult {
  created: number;
  skipped: number;
  ids: string[];
}

/** M2: 知识条目 wire 格式（snake_case） */
export interface KnowledgeEntryProposalWire {
  content: string;
  category: string;
  importance: number;
  source_message_ids: string[];
  reasoning?: string | null;
}

/** M2: 知识提取预览响应 wire 格式 */
export interface ExtractKnowledgeWire {
  reasoning: string;
  entries: KnowledgeEntryProposalWire[];
  project_key: string;
}

/** M2: 知识确认响应 wire 格式 */
export interface ConfirmKnowledgeWire {
  created: number;
  skipped: number;
  ids: string[];
}

/** M2: 映射知识条目 wire -> camelCase */
export function mapKnowledgeEntryProposal(w: KnowledgeEntryProposalWire): KnowledgeEntryProposal {
  return {
    content: w.content,
    category: w.category,
    importance: w.importance,
    sourceMessageIds: w.source_message_ids ?? [],
    reasoning: w.reasoning ?? null,
  };
}

/** M2: 映射知识提取预览响应 */
export function mapExtractKnowledge(w: ExtractKnowledgeWire): ExtractKnowledgeResult {
  return {
    reasoning: w.reasoning,
    entries: w.entries.map(mapKnowledgeEntryProposal),
    projectKey: w.project_key,
  };
}

/** M2: 映射知识确认响应 */
export function mapConfirmKnowledge(w: ConfirmKnowledgeWire): ConfirmKnowledgeResult {
  return {
    created: w.created,
    skipped: w.skipped,
    ids: w.ids,
  };
}

// ── M3: 项目进度顾问 (2026-10-12) ───────────────────────────────────────────

/** M3: 顾问识别的风险项（camelCase） */
export interface AdvisorRisk {
  description: string;
  severity: string;
  suggestion?: string | null;
}

/** M3: 顾问给出的改进建议（camelCase） */
export interface AdvisorSuggestion {
  action: string;
  reason?: string | null;
  priority: string;
}

/** M3: 顾问分析结果（camelCase） */
export interface AdviceResult {
  healthScore: number;
  summary: string;
  risks: AdvisorRisk[];
  suggestions: AdvisorSuggestion[];
  cachedAt?: number | null;
}

/** M3: 风险项 wire 格式（snake_case） */
export interface AdvisorRiskWire {
  description: string;
  severity: string;
  suggestion?: string | null;
}

/** M3: 建议项 wire 格式（snake_case） */
export interface AdvisorSuggestionWire {
  action: string;
  reason?: string | null;
  priority: string;
}

/** M3: 顾问分析响应 wire 格式 */
export interface AdviceWire {
  health_score: number;
  summary: string;
  risks: AdvisorRiskWire[];
  suggestions: AdvisorSuggestionWire[];
  cached_at?: number | null;
}

/** M3: 映射风险项 wire -> camelCase */
export function mapAdvisorRisk(w: AdvisorRiskWire): AdvisorRisk {
  return {
    description: w.description,
    severity: w.severity,
    suggestion: w.suggestion ?? null,
  };
}

/** M3: 映射建议项 wire -> camelCase */
export function mapAdvisorSuggestion(w: AdvisorSuggestionWire): AdvisorSuggestion {
  return {
    action: w.action,
    reason: w.reason ?? null,
    priority: w.priority,
  };
}

/** M3: 映射顾问分析响应 wire -> camelCase */
export function mapAdvice(w: AdviceWire): AdviceResult {
  return {
    healthScore: w.health_score,
    summary: w.summary,
    risks: w.risks.map(mapAdvisorRisk),
    suggestions: w.suggestions.map(mapAdvisorSuggestion),
    cachedAt: w.cached_at ?? null,
  };
}

// ── M5: 代码→Wiki 生成 (2026-10-12) ─────────────────────────────────────────

/** M5: Wiki 生成请求 */
export interface WikiGeneratePayload {
  incremental: boolean;
}

/** M5: Wiki 生成结果（camelCase） */
export interface WikiGenerateResult {
  pagesGenerated: number;
  pagesUpdated: number;
  pagesSkipped: number;
  errors: string[];
  wikiPaths: string[];
}

/** M5: 文件扫描结果项（camelCase） */
export interface ScannedFile {
  path: string;
  language: string;
  sizeBytes: number;
  contentHash: string;
}

/** M5: 文件扫描结果 */
export interface FileScanResult {
  files: ScannedFile[];
  total: number;
}

/** M5: 符号信息（camelCase） */
export interface ExtractedSymbol {
  name: string;
  kind: string;
  lineno: number;
  endLineno: number | null;
  docstring: string | null;
  decorators: string[];
  parent: string | null;
  filePath: string;
  args: string[];
  returnType: string | null;
  bases: string[];
}

/** M5: 符号提取结果 */
export interface SymbolExtractResult {
  symbols: ExtractedSymbol[];
  total: number;
}

/** M5: Wiki 生成 wire 格式（snake_case） */
export interface WikiGenerateWire {
  pages_generated: number;
  pages_updated: number;
  pages_skipped: number;
  errors: string[];
  wiki_paths: string[];
}

/** M5: 文件扫描 wire 格式 */
export interface FileScanWire {
  files: Array<{
    path: string;
    language: string;
    size_bytes: number;
    content_hash: string;
  }>;
  total: number;
}

/** M5: 符号提取 wire 格式 */
export interface SymbolExtractWire {
  symbols: Array<{
    name: string;
    kind: string;
    lineno: number;
    end_lineno: number | null;
    docstring: string | null;
    decorators: string[];
    parent: string | null;
    file_path: string;
    args: string[];
    return_type: string | null;
    bases: string[];
  }>;
  total: number;
}

/** M5: 映射 Wiki 生成结果 wire -> camelCase */
export function mapWikiGenerate(w: WikiGenerateWire): WikiGenerateResult {
  return {
    pagesGenerated: w.pages_generated,
    pagesUpdated: w.pages_updated,
    pagesSkipped: w.pages_skipped,
    errors: w.errors,
    wikiPaths: w.wiki_paths,
  };
}

/** M5: 映射扫描文件 wire -> camelCase */
function mapScannedFile(f: FileScanWire['files'][number]): ScannedFile {
  return {
    path: f.path,
    language: f.language,
    sizeBytes: f.size_bytes,
    contentHash: f.content_hash,
  };
}

/** M5: 映射文件扫描结果 wire -> camelCase */
export function mapFileScan(w: FileScanWire): FileScanResult {
  return {
    files: w.files.map(mapScannedFile),
    total: w.total,
  };
}

/** M5: 映射符号 wire -> camelCase */
function mapExtractedSymbol(s: SymbolExtractWire['symbols'][number]): ExtractedSymbol {
  return {
    name: s.name,
    kind: s.kind,
    lineno: s.lineno,
    endLineno: s.end_lineno,
    docstring: s.docstring,
    decorators: s.decorators,
    parent: s.parent,
    filePath: s.file_path,
    args: s.args,
    returnType: s.return_type,
    bases: s.bases,
  };
}

/** M5: 映射符号提取结果 wire -> camelCase */
export function mapSymbolExtract(w: SymbolExtractWire): SymbolExtractResult {
  return {
    symbols: w.symbols.map(mapExtractedSymbol),
    total: w.total,
  };
}

// ── M4: 语义检索 (2026-10-12) ─────────────────────────────────────────────

/** M4: 语义检索结果单项 */
export interface SemanticSearchHit {
  materialId: string;
  chunkIndex: number;
  content: string;
  score: number;
  projectId: string;
}

/** M4: 语义检索结果 */
export interface SemanticSearchResult {
  results: SemanticSearchHit[];
  total: number;
  embedderType: string;
  embedderDims: number;
}

/** M4: 索引统计 */
export interface IndexingStats {
  totalMaterials: number;
  indexedMaterials: number;
  pendingMaterials: number;
  failedMaterials: number;
  totalChunks: number;
  embedderType: string;
  embedderDims: number;
}

/** M4: 语义检索 wire 格式 */
export interface SemanticSearchWire {
  results: Array<{
    material_id: string;
    chunk_index: number;
    content: string;
    score: number;
    project_id: string;
  }>;
  total: number;
  embedder_type: string;
  embedder_dims: number;
}

/** M4: 索引统计 wire 格式 */
export interface IndexingStatsWire {
  total_materials: number;
  indexed_materials: number;
  pending_materials: number;
  failed_materials: number;
  total_chunks: number;
  embedder_type: string;
  embedder_dims: number;
}

/** M4: 映射语义检索结果 wire -> camelCase */
export function mapSemanticSearch(w: SemanticSearchWire): SemanticSearchResult {
  return {
    results: w.results.map((r) => ({
      materialId: r.material_id,
      chunkIndex: r.chunk_index,
      content: r.content,
      score: r.score,
      projectId: r.project_id,
    })),
    total: w.total,
    embedderType: w.embedder_type,
    embedderDims: w.embedder_dims,
  };
}

/** M4: 映射索引统计 wire -> camelCase */
export function mapIndexingStats(w: IndexingStatsWire): IndexingStats {
  return {
    totalMaterials: w.total_materials,
    indexedMaterials: w.indexed_materials,
    pendingMaterials: w.pending_materials,
    failedMaterials: w.failed_materials,
    totalChunks: w.total_chunks,
    embedderType: w.embedder_type,
    embedderDims: w.embedder_dims,
  };
}
// ── AI 治理分析 (2026-10-27) ────────────────────────────────────────────────

/** 画像中的单个源码采样（wire）。响应不回传 content，故可为空串 */
export interface SourceSampleWire {
  path: string;
  language: string;
  lines: number;
  content: string;
}

/** 画像中的 Git 统计（wire） */
export interface GitStatsWire {
  is_repo: boolean;
  current_branch: string | null;
  commit_count: number;
  recent_commit_count: number;
  branch_count: number;
  last_commit_at: string | null;
  dirty_files: number;
}

/** 代码库确定性画像（wire） */
export interface CodebaseProfileWire {
  root: string;
  level1_type: string | null;
  sub_type: string | null;
  tech_stack: string[];
  frameworks: string[];
  build_commands: string[];
  test_frameworks: string[];
  lint_configs: string[];
  ci_workflows: string[];
  existing_rule_files: string[];
  directory_layout: string[];
  source_samples: SourceSampleWire[];
  git_stats: GitStatsWire;
  vcs_mode: string;
}

/** 分析报告中的单条规则建议（wire） */
export interface SuggestedRuleWire {
  template_key: string;
  label: string;
  reason: string;
  confidence: number;
  category: string;
  content: string;
  trigger_pattern: string;
  priority: number;
}

/** 分析报告引用的文档（wire） */
export interface DocRefWire {
  title: string;
  reason: string;
  path: string;
}

/** LLM 深度分析报告（wire） */
export interface AnalysisReportWire {
  level1_type: string;
  sub_type: string | null;
  confidence: number;
  tech_stack: string[];
  architecture_summary: string;
  suggested_rules: SuggestedRuleWire[];
  governance_recommendations: string[];
  stage_recommendation: string | null;
  sage_md_draft: string;
  docs_refs: DocRefWire[];
  llm_available: boolean;
  raw_json: string | null;
}

/** POST /projects/analyze 响应（wire） */
export interface ProjectAnalyzeWire {
  profile: CodebaseProfileWire;
  report: AnalysisReportWire;
}

/** 规则草稿（wire） */
export interface RuleDraftWire {
  category: string;
  content: string;
  trigger_pattern: string;
  priority: number;
  source: string;
  template_key: string;
  reason: string;
}

/** 规则生成结果（wire） */
export interface RuleGenerationResultWire {
  rules: RuleDraftWire[];
  milestones: Array<Record<string, string>>;
  llm_available: boolean;
  skipped_duplicates: number;
}

/** 单个 L2 子类型定义（wire） */
export interface SubTypeDefinitionWire {
  key: string;
  label: string;
  description: string;
  suggested_templates: string[];
  stage: string | null;
  doc_topics: string[];
}

/** GET /projects/sub-types 响应（wire） */
export interface SubTypesWire {
  level1_types: string[];
  sub_types: Record<string, SubTypeDefinitionWire[]>;
}

/** 源码采样（camelCase） */
export interface SourceSample {
  path: string;
  language: string;
  lines: number;
  content: string;
}

/** Git 统计（camelCase） */
export interface GitStats {
  isRepo: boolean;
  currentBranch: string | null;
  commitCount: number;
  recentCommitCount: number;
  branchCount: number;
  lastCommitAt: string | null;
  dirtyFiles: number;
}

/** 代码库画像（camelCase） */
export interface CodebaseProfile {
  root: string;
  level1Type: ProjectType | null;
  subType: string | null;
  techStack: string[];
  frameworks: string[];
  buildCommands: string[];
  testFrameworks: string[];
  lintConfigs: string[];
  ciWorkflows: string[];
  existingRuleFiles: string[];
  directoryLayout: string[];
  sourceSamples: SourceSample[];
  gitStats: GitStats;
  vcsMode: string;
}

/** 规则建议（camelCase） */
export interface SuggestedRule {
  templateKey: string;
  label: string;
  reason: string;
  confidence: number;
  category: string;
  content: string;
  triggerPattern: string;
  priority: number;
}

/** 文档引用（camelCase） */
export interface DocRef {
  title: string;
  reason: string;
  path: string;
}

/** LLM 深度分析报告（camelCase） */
export interface AnalysisReport {
  level1Type: ProjectType;
  subType: string | null;
  confidence: number;
  techStack: string[];
  architectureSummary: string;
  suggestedRules: SuggestedRule[];
  governanceRecommendations: string[];
  stageRecommendation: string | null;
  sageMdDraft: string;
  docsRefs: DocRef[];
  /** false 表示报告来自确定性降级路径（未配置 LLM 或调用失败） */
  llmAvailable: boolean;
  rawJson: string | null;
}

/** 分析结果：画像 + 报告（camelCase） */
export interface ProjectAnalysisResult {
  profile: CodebaseProfile;
  report: AnalysisReport;
}

/** 规则来源：模板规则 / 项目专属规则 */
export type RuleSource = 'template' | 'ai_custom';

/** 规则草稿（camelCase） */
export interface RuleDraft {
  category: string;
  content: string;
  triggerPattern: string;
  priority: number;
  source: RuleSource;
  templateKey: string;
  reason: string;
}

/** 规则生成结果（camelCase） */
export interface RuleGenerationResult {
  rules: RuleDraft[];
  milestones: Array<Record<string, string>>;
  llmAvailable: boolean;
  skippedDuplicates: number;
}

/** L2 子类型定义（camelCase） */
export interface SubTypeDefinition {
  key: string;
  label: string;
  description: string;
  suggestedTemplates: string[];
  stage: string | null;
  docTopics: string[];
}

/** 两级类型目录（camelCase） */
export interface SubTypesCatalog {
  level1Types: ProjectType[];
  subTypes: Record<string, SubTypeDefinition[]>;
}

/** `generateRules()` 入参：用户在向导中确认后的画像与报告 */
export interface GenerateRulesOptions {
  profile: CodebaseProfile;
  report: AnalysisReport;
  /** 提供时后端会与该项目的已有约束去重 */
  projectId?: string;
}

const LEVEL1_PROJECT_TYPES: ProjectType[] = ['coding', 'research', 'business', 'personal'];

/**
 * 后端/LLM 返回的类型字符串可能越界，收敛到四值 union。
 * 与 detectType() 的既有降级口径保持一致（未知 → personal）。
 */
function toProjectType(value: string | null | undefined): ProjectType {
  return LEVEL1_PROJECT_TYPES.includes(value as ProjectType) ? (value as ProjectType) : 'personal';
}

export function mapSourceSample(w: SourceSampleWire): SourceSample {
  return { path: w.path, language: w.language, lines: w.lines, content: w.content };
}

export function mapGitStats(w: GitStatsWire): GitStats {
  return {
    isRepo: w.is_repo,
    currentBranch: w.current_branch,
    commitCount: w.commit_count,
    recentCommitCount: w.recent_commit_count,
    branchCount: w.branch_count,
    lastCommitAt: w.last_commit_at,
    dirtyFiles: w.dirty_files,
  };
}

export function mapCodebaseProfile(w: CodebaseProfileWire): CodebaseProfile {
  return {
    root: w.root,
    level1Type: w.level1_type === null ? null : toProjectType(w.level1_type),
    subType: w.sub_type,
    techStack: w.tech_stack,
    frameworks: w.frameworks,
    buildCommands: w.build_commands,
    testFrameworks: w.test_frameworks,
    lintConfigs: w.lint_configs,
    ciWorkflows: w.ci_workflows,
    existingRuleFiles: w.existing_rule_files,
    directoryLayout: w.directory_layout,
    sourceSamples: w.source_samples.map(mapSourceSample),
    gitStats: mapGitStats(w.git_stats),
    vcsMode: w.vcs_mode,
  };
}

export function mapSuggestedRule(w: SuggestedRuleWire): SuggestedRule {
  return {
    templateKey: w.template_key,
    label: w.label,
    reason: w.reason,
    confidence: w.confidence,
    category: w.category,
    content: w.content,
    triggerPattern: w.trigger_pattern,
    priority: w.priority,
  };
}

export function mapDocRef(w: DocRefWire): DocRef {
  return { title: w.title, reason: w.reason, path: w.path };
}

export function mapAnalysisReport(w: AnalysisReportWire): AnalysisReport {
  return {
    level1Type: toProjectType(w.level1_type),
    subType: w.sub_type,
    confidence: w.confidence,
    techStack: w.tech_stack,
    architectureSummary: w.architecture_summary,
    suggestedRules: w.suggested_rules.map(mapSuggestedRule),
    governanceRecommendations: w.governance_recommendations,
    stageRecommendation: w.stage_recommendation,
    sageMdDraft: w.sage_md_draft,
    docsRefs: w.docs_refs.map(mapDocRef),
    llmAvailable: w.llm_available,
    rawJson: w.raw_json,
  };
}

export function mapProjectAnalysis(w: ProjectAnalyzeWire): ProjectAnalysisResult {
  return {
    profile: mapCodebaseProfile(w.profile),
    report: mapAnalysisReport(w.report),
  };
}

export function mapRuleDraft(w: RuleDraftWire): RuleDraft {
  return {
    category: w.category,
    content: w.content,
    triggerPattern: w.trigger_pattern,
    priority: w.priority,
    source: w.source === 'ai_custom' ? 'ai_custom' : 'template',
    templateKey: w.template_key,
    reason: w.reason,
  };
}

export function mapRuleGenerationResult(w: RuleGenerationResultWire): RuleGenerationResult {
  return {
    rules: w.rules.map(mapRuleDraft),
    milestones: w.milestones,
    llmAvailable: w.llm_available,
    skippedDuplicates: w.skipped_duplicates,
  };
}

export function mapSubTypeDefinition(w: SubTypeDefinitionWire): SubTypeDefinition {
  return {
    key: w.key,
    label: w.label,
    description: w.description,
    suggestedTemplates: w.suggested_templates,
    stage: w.stage,
    docTopics: w.doc_topics,
  };
}

export function mapSubTypes(w: SubTypesWire): SubTypesCatalog {
  const subTypes: Record<string, SubTypeDefinition[]> = {};
  for (const [level1, defs] of Object.entries(w.sub_types)) {
    subTypes[level1] = defs.map(mapSubTypeDefinition);
  }
  return {
    level1Types: w.level1_types.map(toProjectType),
    subTypes,
  };
}

/**
 * 反向映射：camelCase 画像 -> wire dict。
 * `/projects/generate-rules` 接收原始 snake_case dict（后端 `_profile_from_dict` 口径），
 * 这里把用户可能改动过的画像还原后再提交。
 */
export function toCodebaseProfileWire(p: CodebaseProfile): CodebaseProfileWire {
  return {
    root: p.root,
    level1_type: p.level1Type,
    sub_type: p.subType,
    tech_stack: p.techStack,
    frameworks: p.frameworks,
    build_commands: p.buildCommands,
    test_frameworks: p.testFrameworks,
    lint_configs: p.lintConfigs,
    ci_workflows: p.ciWorkflows,
    existing_rule_files: p.existingRuleFiles,
    directory_layout: p.directoryLayout,
    source_samples: p.sourceSamples.map((s) => ({
      path: s.path,
      language: s.language,
      lines: s.lines,
      content: s.content,
    })),
    git_stats: {
      is_repo: p.gitStats.isRepo,
      current_branch: p.gitStats.currentBranch,
      commit_count: p.gitStats.commitCount,
      recent_commit_count: p.gitStats.recentCommitCount,
      branch_count: p.gitStats.branchCount,
      last_commit_at: p.gitStats.lastCommitAt,
      dirty_files: p.gitStats.dirtyFiles,
    },
    vcs_mode: p.vcsMode,
  };
}

/** 反向映射：camelCase 分析报告 -> wire dict */
export function toAnalysisReportWire(r: AnalysisReport): AnalysisReportWire {
  return {
    level1_type: r.level1Type,
    sub_type: r.subType,
    confidence: r.confidence,
    tech_stack: r.techStack,
    architecture_summary: r.architectureSummary,
    suggested_rules: r.suggestedRules.map((rule) => ({
      template_key: rule.templateKey,
      label: rule.label,
      reason: rule.reason,
      confidence: rule.confidence,
      category: rule.category,
      content: rule.content,
      trigger_pattern: rule.triggerPattern,
      priority: rule.priority,
    })),
    governance_recommendations: r.governanceRecommendations,
    stage_recommendation: r.stageRecommendation,
    sage_md_draft: r.sageMdDraft,
    docs_refs: r.docsRefs.map((ref) => ({
      title: ref.title,
      reason: ref.reason,
      path: ref.path,
    })),
    llm_available: r.llmAvailable,
    raw_json: r.rawJson,
  };
}

export function auditProjectApiTypesGovernance(): string {
  return JSON.stringify({
    module: 'project-api-types',
    phase: 'P188',
    audited: true,
  });
}
