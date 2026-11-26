/**
 * 声明式外部服务 UI 规格：与后端 ExternalServiceSpec 呼应。
 * 通用卡片按 fields 渲染表单、按 fetchStatus / statusEndpoint 展示状态，
 * 具体服务只需提供一份 spec。
 */

import type { ReactNode } from 'react';

import type { PreferenceKey } from '../../../shared/api/settingsClient';

export type ExternalServiceFieldType = 'text' | 'password' | 'number' | 'boolean';

export interface ExternalServiceField {
  jsonKey: string;
  label: string;
  type: ExternalServiceFieldType;
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
}

export interface ExternalServiceStatus {
  configured: boolean;
  enabled: boolean;
  hasApiKey: boolean;
  reachable: boolean;
  reason: string;
  error?: string;
  serverAuthMode?: string;
  serverTiers?: string[] | null;
  serverVersion?: string | null;
}

export type ExternalServiceConfig = Record<string, string | number | boolean>;

export interface ExternalServiceUiSpec {
  key: PreferenceKey;
  title: string;
  description: string;
  fields: ExternalServiceField[];
  defaults: ExternalServiceConfig;
  statusEndpoint: string;
  testId?: string;
  /** 直接给定状态请求（如复用既有 API 客户端）；缺省走 statusEndpoint。 */
  fetchStatus?: () => Promise<ExternalServiceStatus> | ExternalServiceStatus;
  /** 服务专属状态区渲染；缺省用通用「可达/不可达」文案。 */
  renderStatus?: (status: ExternalServiceStatus, config: ExternalServiceConfig) => ReactNode;
}
