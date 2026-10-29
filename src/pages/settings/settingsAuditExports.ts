/**
 * 设置页「审计导出」数据源（P3，2026-10-29）。
 *
 * P3 之前，每个 tab 里各有一个「复制摘要 / 复制 JSON」小按钮（11 个文件、
 * 17 处）。它们有三个问题：
 *
 * 1. **噪音**：17 个按钮散落在设置页各处，占位又长得像可点的功能；
 * 2. **不可发现**：用户遇到问题想「把当前配置发出去」时，不知道该点哪个；
 * 3. **语义不统一**：有的抄瞬时 UI 状态（正在编辑哪条端点），有的抄持久化配置。
 *
 * 本模块把审计能力收敛到一处：每个 section 是一个采集器，负责把该区块的
 * **当前生效状态** 读出来，交给既有的 `formatXxxAuditSnapshot/Json` 纯函数
 * 渲染成两种格式。
 *
 * ### 语义约定：集中导出不抄瞬时 UI 选择
 *
 * 集中导出只抄「配置 + 运行状态快照」，**不含瞬时 UI 选择**（正在编辑哪条
 * 端点、当前搜索词、选中了哪个运行时、正在测试哪条连接）。原来的页内按钮
 * 能采到它们，是因为它就长在那个上下文里；集中导出时这些值没有对应上下文，
 * 一律取中性值。
 *
 * 受影响字段：
 *
 * - `EndpointsTab` `editingId` / `testingId` → 传 `null`
 * - `McpTab` `loading` / `hasError` → 传 `false`（采集完成即 idle）
 * - `NetworkTab` `primaryEngine` → 从持久化 preference 读（不是 UI state）
 * - `PromptTemplatesTab` `loading` / `editing` / `hasConflict` → 传 `false`
 * - `RuntimeEnvTab` `probeKind` / `diagnoseKind` / `execKind` / `selectedRuntime`
 *   → 传中性值（`'idle'` / `null`）
 * - `ZoteroTab` `query` / `selectedCollectionKey` / `selectedTag` → 传空/`null`
 *
 * 这些中性值不是缺陷 —— 导出的是「此刻生效配置」，没有用户正在做什么。
 *
 * ### 包体积考虑
 *
 * 本模块通过 `AuditExportTab.tsx` 被 `settingsTabs.tsx` 注册表渲染 ——
 * 仅当用户切到审计导出 tab 时才加载。`CommandPalette` 只引用
 * `settingsSearchIndex.ts`，与 `settingsTabs.tsx` 没有运行时依赖。
 * 本文件对 `settingsTabs` 只使用 `import type`，编译期擦除。
 */

import { useCallback, useMemo, useState } from 'react';

import { useSettingsStore } from '../../features/manage-settings/settingsStore';
import { invoke } from '../../shared/api/desktopInvoke';
import { mcpClient } from '../../shared/api/mcpClient';
import { promptApi } from '../../shared/api/promptApi';
import { runtimeApi } from '../../shared/api/runtimeApi';
import { settingsClient } from '../../shared/api/settingsClient';
import { zoteroClient } from '../../shared/api/zoteroClient';
import type { TranslationKey } from '../../shared/lib/i18n';
import { isFeatureUnlocked } from '../../shared/lib/hooks/useFeatureUnlock';

import {
  formatArenaAccountsToggleAuditJson,
  formatArenaAccountsToggleAuditSnapshot,
} from './ArenaAccountsToggle';
import {
  formatBasicTabAuditJson,
  formatBasicTabAuditSnapshot,
} from './BasicTab';
import {
  formatEndpointsTabAuditJson,
  formatEndpointsTabAuditSnapshot,
} from './EndpointsTab';
import { formatMcpTabAuditJson, formatMcpTabAuditSnapshot } from './McpTab';
import {
  formatMemoryTabAuditJson,
  formatMemoryTabAuditSnapshot,
} from './MemoryTab';
import {
  formatModelsTabAuditJson,
  formatModelsTabAuditSnapshot,
} from './ModelsTab';
import {
  formatNetworkTabAuditJson,
  formatNetworkTabAuditSnapshot,
  type NetworkMode,
} from './NetworkTab';
import {
  formatOrchestrationTabAuditJson,
  formatOrchestrationTabAuditSnapshot,
} from './OrchestrationTab';
import {
  formatPromptTemplatesTabAuditJson,
  formatPromptTemplatesTabAuditSnapshot,
} from './PromptTemplatesTab';
import {
  formatRuntimeEnvTabAuditJson,
  formatRuntimeEnvTabAuditSnapshot,
} from './RuntimeEnvTab';
import {
  formatSkillsTabAuditJson,
  formatSkillsTabAuditSnapshot,
} from './SkillsTab';
import type { SettingsTabKey } from './settingsTabs';
import {
  formatZoteroTabAuditJson,
  formatZoteroTabAuditSnapshot,
} from './ZoteroTab';

/** 单节审计的两种格式输出。 */
export interface SettingsAuditPayload {
  /** 人类可读的 Markdown 摘要。 */
  snapshot: string;
  /** 机器可读的 JSON 字符串。 */
  json: string;
}

/** 单节审计定义。`collect` 异步 —— 多数数据来自 IPC 或偏好存储。 */
export interface SettingsAuditSectionDef {
  id: string;
  /** 该节所属的设置 tab，UI 按 tab 分组展示。 */
  tab: SettingsTabKey;
  labelKey: TranslationKey;
  collect: () => Promise<SettingsAuditPayload>;
}

/** 安全解析 preferences 表的 JSON 字符串；非法或缺失一律返回 `null`。 */
function parseJson<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

/** 读取 zustand 全局 store 当前 settings。在异步采集器内安全（不订阅）。 */
function currentSettings() {
  return useSettingsStore.getState().settings;
}

// 每个 section 的 collect 都是「读 → 过 format* 纯函数」。
// 中性值的含义见模块顶部 JSDoc：集中导出不抄 UI 瞬时态。
export const SETTINGS_AUDIT_SECTIONS: readonly SettingsAuditSectionDef[] = [
  {
    id: 'basic',
    tab: 'basic',
    labelKey: 'settings.audit.section.basic',
    collect: async () => {
      const s = currentSettings();
      const input = {
        streaming: Boolean(s.streaming),
        llmRetryMaxAttempts: Number(s.llmRetryMaxAttempts),
        llmRetryBaseDelayS: Number(s.llmRetryBaseDelayS),
        llmRetryMaxDelayS: Number(s.llmRetryMaxDelayS),
        llmTotalTimeoutS: Number(s.llmTotalTimeoutS),
        llmProxyTimeoutS: Number(s.llmProxyTimeoutS),
        timezone: s.timezone || '',
        logTimezone: s.logTimezone || '',
        demoMode: Boolean(s.demoMode),
      };
      return {
        snapshot: formatBasicTabAuditSnapshot(input),
        json: formatBasicTabAuditJson(input),
      };
    },
  },
  {
    id: 'models',
    tab: 'models-services',
    labelKey: 'settings.audit.section.models',
    collect: async () => {
      const s = currentSettings();
      const endpoints = s.endpoints ?? [];
      const discoveredModelCount = endpoints.reduce(
        (n, ep) => n + (ep.discoveredModels?.length ?? 0),
        0,
      );
      const input = {
        endpointCount: endpoints.length,
        discoveredModelCount,
        chatModel: s.modelSelections?.chatModel?.modelId ?? null,
        visionModel: s.modelSelections?.visionModel?.modelId ?? null,
        embeddingModel: s.modelSelections?.embeddingModel?.modelId ?? null,
        maxContext: Number(s.maxContext),
        autoContext: Boolean(s.autoContext),
        temperature: Number(s.temperature),
      };
      return {
        snapshot: formatModelsTabAuditSnapshot(input),
        json: formatModelsTabAuditJson(input),
      };
    },
  },
  {
    id: 'endpoints',
    tab: 'models-services',
    labelKey: 'settings.audit.section.endpoints',
    collect: async () => {
      const s = currentSettings();
      // 集中导出不抄瞬时 UI 选择（editingId/testingId 在页内按钮里有上下文，
      // 集中导出没有 → 传 null，与 EndpointsTab 的 type 签名一致）。
      const input = {
        endpointCount: (s.endpoints ?? []).length,
        editingId: null as string | null,
        testingId: null as string | null,
      };
      return {
        snapshot: formatEndpointsTabAuditSnapshot(input),
        json: formatEndpointsTabAuditJson(input),
      };
    },
  },
  {
    id: 'arena-accounts',
    tab: 'models-services',
    labelKey: 'settings.audit.section.arena',
    collect: async () => {
      // 解锁态存在 localStorage（渐进式披露），用命令式读取器取当前值。
      const input = { enabled: isFeatureUnlocked('arena-accounts') };
      return {
        snapshot: formatArenaAccountsToggleAuditSnapshot(input),
        json: formatArenaAccountsToggleAuditJson(input),
      };
    },
  },
  {
    id: 'orchestration',
    tab: 'orchestration',
    labelKey: 'settings.audit.section.orchestration',
    collect: async () => {
      const o = currentSettings().orch;
      const input = {
        planPreflightEnabled: Boolean(o.planPreflightEnabled),
        planScoutEnabled: Boolean(o.planScoutEnabled),
        maxScoutIterations: Number(o.maxScoutIterations),
        maxPlannerIterations: Number(o.maxPlannerIterations),
        maxConcurrentSubagents: Number(o.maxConcurrentSubagents),
        maxRetries: Number(o.maxRetries),
        maxLaneIterations: Number(o.maxLaneIterations),
        maxSubagentIterations: Number(o.maxSubagentIterations),
        subagentApprovalMode: String(o.subagentApprovalMode),
        worktreeIsolation: Boolean(o.worktreeIsolation),
        scratchRoot: String(o.scratchRoot ?? ''),
      };
      return {
        snapshot: formatOrchestrationTabAuditSnapshot(input),
        json: formatOrchestrationTabAuditJson(input),
      };
    },
  },
  {
    id: 'skills',
    tab: 'plugins-skills',
    labelKey: 'settings.audit.section.skills',
    collect: async () => {
      const [script, dir] = await Promise.all([
        settingsClient.getPreference('allow_skill_scripts'),
        settingsClient.getPreference('skills_dir'),
      ]);
      const input = {
        allow_skill_scripts: script === '1',
        skills_dir: dir ?? '',
      };
      return {
        snapshot: formatSkillsTabAuditSnapshot(input),
        json: formatSkillsTabAuditJson(input),
      };
    },
  },
  {
    id: 'network',
    tab: 'network',
    labelKey: 'settings.audit.section.network',
    collect: async () => {
      const [policyRaw, proxyRaw, searchRaw] = await Promise.all([
        settingsClient.getPreference('network_policy'),
        settingsClient.getPreference('web_proxy'),
        settingsClient.getPreference('search_config'),
      ]);
      const policy = parseJson<{
        mode?: string;
        allowed_hosts?: string[];
        insecure_tls_hosts?: string[];
      }>(policyRaw);
      const proxy = parseJson<{ http?: string; https?: string }>(proxyRaw);
      const search = parseJson<{ order?: string[] }>(searchRaw);
      const input = {
        mode: (policy?.mode ?? 'online') as NetworkMode,
        allowedCount: policy?.allowed_hosts?.length ?? 0,
        insecureTlsCount: policy?.insecure_tls_hosts?.length ?? 0,
        hasProxy: Boolean(proxy?.http || proxy?.https),
        primaryEngine: search?.order?.[0] ?? null,
      };
      return {
        snapshot: formatNetworkTabAuditSnapshot(input),
        json: formatNetworkTabAuditJson(input),
      };
    },
  },
  {
    id: 'mcp',
    tab: 'mcp',
    labelKey: 'settings.audit.section.mcp',
    collect: async () => {
      const report = await mcpClient.status();
      const servers = report?.servers ?? [];
      const input = {
        serverCount: servers.length,
        readyCount: servers.filter((s) => s.state === 'ready').length,
        // 集中导出时已完成采集，无「正在加载」语义；hasError 只在页内按钮
        // 提示「此刻 UI 有错」时用，集中导出直接省略。
        loading: false,
        hasError: false,
      };
      return {
        snapshot: formatMcpTabAuditSnapshot(input),
        json: formatMcpTabAuditJson(input),
      };
    },
  },
  {
    id: 'memory',
    tab: 'memory',
    labelKey: 'settings.audit.section.memory',
    collect: async () => {
      // 与 MemoryTab 的 loadStatus 同形（IPC 命令名 / 字段名一一对应）。
      const embedder = await invoke<{
        type: string;
        semantic: boolean;
        model_ready: boolean;
      } | null>('embedder_get_status');
      const backups = await invoke<{
        backups: { name: string; size_bytes: number; created_at: number }[];
      }>('system_backups_list');
      const input = {
        embedderType: embedder?.type ?? null,
        semantic: Boolean(embedder?.semantic),
        modelReady: Boolean(embedder?.model_ready),
        backupCount: backups?.backups?.length ?? 0,
      };
      return {
        snapshot: formatMemoryTabAuditSnapshot(input),
        json: formatMemoryTabAuditJson(input),
      };
    },
  },
  {
    id: 'zotero',
    tab: 'zotero',
    labelKey: 'settings.audit.section.zotero',
    collect: async () => {
      const s = await zoteroClient.status();
      // ZoteroTab 里 `collectionCount` 有 fallback：stats.collections 缺失时
      // 退回到本地缓存的 collections.length。集中导出没缓存，直接取 0。
      const input = {
        connected: Boolean(s?.available),
        statusLoading: false,
        itemCount: Number(s?.stats?.items ?? 0),
        collectionCount: Number(s?.stats?.collections ?? 0),
        // 集中导出不抄搜索/筛选 UI 状态（同 endpoints 的中性值逻辑）。
        searchResultCount: 0,
        query: '',
        selectedCollectionKey: null as string | null,
        selectedTag: null as string | null,
      };
      return {
        snapshot: formatZoteroTabAuditSnapshot(input),
        json: formatZoteroTabAuditJson(input),
      };
    },
  },
  {
    id: 'runtime',
    tab: 'runtime',
    labelKey: 'settings.audit.section.runtime',
    collect: async () => {
      const probe = await runtimeApi.probe();
      const input = {
        // 集中导出时 probe 已经返回 —— 不再抄页内 UI 选择
        // （probeKind/diagnoseKind/execKind 是 tab 内部的按钮态）。
        probeKind: 'idle',
        runtimeCount: probe?.output?.runtimes?.length ?? 0,
        selectedRuntime: null as string | null,
        diagnoseKind: 'idle',
        execKind: 'idle',
      };
      return {
        snapshot: formatRuntimeEnvTabAuditSnapshot(input),
        json: formatRuntimeEnvTabAuditJson(input),
      };
    },
  },
  {
    id: 'prompt-templates',
    tab: 'memory',
    labelKey: 'settings.audit.section.promptTemplates',
    collect: async () => {
      const templates = await promptApi.list();
      const input = {
        templateCount: templates?.length ?? 0,
        // 集中导出不抄 UI 编辑/冲突态。
        loading: false,
        editing: false,
        hasConflict: false,
      };
      return {
        snapshot: formatPromptTemplatesTabAuditSnapshot(input),
        json: formatPromptTemplatesTabAuditJson(input),
      };
    },
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// UI helpers —— 供 AuditExportTab 复用，集中在此避免组件文件膨胀。
// ─────────────────────────────────────────────────────────────────────────────

export type AuditSectionStatus =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; payload: SettingsAuditPayload }
  | { kind: 'error'; message: string };

/**
 * 管理每个 section 的加载 / 缓存状态。
 * - 首次打开 tab 时全部 `idle`；用户点「加载」触发 `collect()`；
 * - 成功 → `ready`（保存 payload），失败 → `error`（保存消息）。
 * - 每个 section 独立状态，刷新一节不影响其他。
 */
export function useAuditSectionStates() {
  const [states, setStates] = useState<Record<string, AuditSectionStatus>>({});

  const get = useCallback(
    (id: string): AuditSectionStatus => states[id] ?? { kind: 'idle' },
    [states],
  );

  const load = useCallback(async (section: SettingsAuditSectionDef) => {
    setStates((prev) => ({ ...prev, [section.id]: { kind: 'loading' } }));
    try {
      const payload = await section.collect();
      setStates((prev) => ({ ...prev, [section.id]: { kind: 'ready', payload } }));
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setStates((prev) => ({ ...prev, [section.id]: { kind: 'error', message } }));
    }
  }, []);

  const loadAll = useCallback(async () => {
    await Promise.all(SETTINGS_AUDIT_SECTIONS.map((s) => load(s)));
  }, [load]);

  return useMemo(() => ({ states, get, load, loadAll }), [states, get, load, loadAll]);
}

/**
 * 把全部已就绪的 section 合并为一份总摘要 / 总 JSON，供「复制全部」使用。
 * 未就绪的 section 跳过，不阻塞整体导出（降级而不是失败）。
 */
export function combineAuditOutputs(
  sections: readonly SettingsAuditSectionDef[],
  get: (id: string) => AuditSectionStatus,
  mode: 'snapshot' | 'json',
  fallback: string,
): string {
  const ready = sections
    .map((s) => ({ section: s, status: get(s.id) }))
    .filter(
      (
        entry,
      ): entry is {
        section: SettingsAuditSectionDef;
        status: { kind: 'ready'; payload: SettingsAuditPayload };
      } => entry.status.kind === 'ready',
    );
  if (ready.length === 0) {
    return mode === 'json' ? '{}' : fallback;
  }
  if (mode === 'json') {
    const combined = Object.fromEntries(
      ready.map(({ section, status }) => [section.id, JSON.parse(status.payload.json)]),
    );
    return JSON.stringify(combined, null, 2);
  }
  return ready
    .map(({ status }) => status.payload.snapshot)
    .join('\n\n---\n\n');
}
