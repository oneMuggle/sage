/**
 * Sage API - 统一导出
 *
 * 将各 API 模块聚合导出，保持向后兼容
 */

// API 模块
export { agentsApi } from './agentsApi';
export { chatApi } from './chatApi';
export { knowledgeApi } from './knowledgeApi';
export { memoryApi } from './memoryApi';
export { messageApi } from './messageApi';
export { officeApi } from './officeApi';
export { sessionApi } from './sessionApi';
export { workspaceApi } from './workspaceApi';
export { skillsApi } from './skillsApi';
export { themeCssClient } from './themeCssClient';
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
  ChatConfig,
  ChatRequest,
  ChatResponse,
  ChatOfficeRef,
  KnowledgeDoc,
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
  SessionWorkspaceBinding,
  Skill,
  SkillDispatch,
  SkillExecuteRequest,
  SkillExecuteResult,
  ToolCall,
  ToolChainSnapshot,
  ToolStepSnapshot,
  UserQuestion,
  WorkspaceSearchKind,
  WorkspaceSearchResponse,
  WorkspaceSearchResult,
  WorkspaceRevokeResponse,
} from './types';

// 工具函数和类
export { ApiException, isValidSessionId, sanitizeInput } from './utils';
