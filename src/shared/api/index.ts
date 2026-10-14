/**
 * Sage API - 统一导出
 *
 * 将各 API 模块聚合导出，保持向后兼容
 */

// API 模块
export { agentsApi } from './agentsApi';
export { chatApi } from './chatApi';
export { knowledgeApi } from './knowledgeApi';
export { learnApi } from './learnApi';
export { memoryApi } from './memoryApi';
export { messageApi } from './messageApi';
export { promptApi } from './promptApi';
export type { PromptTemplate } from './promptApi';
export { projectApi } from './projectApi';
export type {
  ProjectOpenResult,
  ProjectSummary,
  ProjectType,
  ProjectConstraint,
  ProjectMilestone,
  ProjectTypeDetectionResult,
  CreateConstraintPayload,
  UpdateConstraintPayload,
  CreateMilestonePayload,
  UpdateMilestonePayload,
  ProjectScaffoldOptions,
  ProjectScaffoldResult,
  ProjectContextBudget,
  ProjectDiagnoseResult,
  ProjectWorkspaceOverview,
  WorkspaceArtifactItem,
  WorkspaceDirectorySummary,
  // AI 任务分解 M1 (2026-10-12)
  PreviewMilestoneNode,
  DecomposePreviewResult,
  DecomposePreviewPayload,
  DecomposeApplyPayload,
  DecomposeApplyResult,
  // AI 知识沉淀 M2 (2026-10-12)
  KnowledgeEntryProposal,
  ExtractKnowledgeResult,
  ExtractKnowledgePayload,
  ConfirmKnowledgePayload,
  ConfirmKnowledgeResult,
  // AI 项目顾问 M3 (2026-10-12)
  AdvisorRisk,
  AdvisorSuggestion,
  AdviceResult,
  // AI 代码→Wiki 生成 M5 (2026-10-12)
  WikiGeneratePayload,
  WikiGenerateResult,
  ScannedFile,
  FileScanResult,
  ExtractedSymbol,
  SymbolExtractResult,
  // M4: 语义检索 (2026-10-12)
  SemanticSearchHit,
  SemanticSearchResult,
  IndexingStats,
} from './projectApi';
export { officeApi } from './officeApi';
export { sessionApi } from './sessionApi';
export { skillDraftsApi } from './skillDraftsApi';
export { skillsApi } from './skillsApi';
import * as windowControlsClient from './windowControlsClient';
export const windowControls = windowControlsClient.windowControls;
export const getWindowControlsBridge = windowControlsClient.getWindowControlsBridge;
export const createWebControlsBridge = windowControlsClient.createWebControlsBridge;
export const detectPlatform = windowControlsClient.detectPlatform;
export const isElectronDesktop = windowControlsClient.isElectronDesktop;
export type { Platform, WindowControlsBridge } from './windowControlsClient';

// 类型定义
export type {
  AgentEvent,
  AgentProfile,
  AgentState,
  AgentToolCall,
  AgentToolResult,
  AgentUpdate,
  ApiError,
  BoardProjectionEnvelope,
  ChatConfig,
  ChatRequest,
  ChatResponse,
  ChatOfficeRef,
  ConsolidationAcceptResult,
  ConsolidationScanResult,
  ConsolidationSuggestion,
  FreshnessSummaryInfo,
  KnowledgeDoc,
  LearnResponse,
  LaneBoardEntry,
  LaneBoardSnapshot,
  LaneFreshnessInfo,
  Memory,
  Message,
  OfficeDeleteResponse,
  OfficeDocStatus,
  OfficeDocType,
  OfficeDocumentListResponse,
  OfficeDocumentMetadata,
  OfficeDocumentSummary,
  OfficeExcelReadResult,
  OfficeExcelSheetContent,
  OfficePptReadResult,
  OfficePptSlideContent,
  OfficeReadRequest,
  OfficeWordParagraphContent,
  OfficeWordReadResult,
  OfficeWordTableContent,
  PermissionRequest,
  QuestionOption,
  Session,
  SessionCompactResult,
  SessionLineage,
  LineageArchive,
  SessionWorkspaceBinding,
  Skill,
  SkillDispatch,
  SkillDraft,
  SkillDraftApproveResponse,
  SkillDraftListResponse,
  SkillDraftRejectResponse,
  SkillExecuteRequest,
  SkillExecuteResult,
  ReviewVerdict,
  TaskPlanEvent,
  TaskPlanItem,
  TaskProgressEvent,
  TaskReviewEvent,
  SubagentEventPhase,
  SubagentLiveEvent,
  SubagentLiveState,
  TaskStatusEvent,
  TaskStatusValue,
  TodoItem,
  TodoSnapshotEvent,
  TodoStatus,
  ToolCall,
  UserQuestion,
  WorkspaceSearchKind,
  WorkspaceSearchResponse,
  WorkspaceSearchResult,
  WorkspaceRevokeResponse,
} from './types';

// 工具函数和类
export { ApiException, isValidSessionId, sanitizeInput } from './utils';
