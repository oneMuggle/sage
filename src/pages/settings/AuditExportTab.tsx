/**
 * 「审计导出」tab (P3，2026-10-29)。
 *
 * 把原先散落在 11 个 tab 里的 17 个「复制摘要 / 复制 JSON」按钮收进一个
 * 集中面板。用户打开这页后看到每个区块（基础 / 模型 / 端点 / ...）的三态
 * （idle / loading / ready / error），按需采集，一键复制汇总。
 *
 * 设计取舍：
 * - 默认 idle：每个 section 的 `collect()` 涉及 IPC / preference 查询，首次
 *   渲染就全部发起会把设置页打开变成一次「全量抓数据」，且多数用户从不导出。
 *   显式点击才触发，既快又可控。
 * - 汇总降级：「复制全部」只合并已就绪的 section，未就绪的跳过而不是阻塞。
 *   用户看到的是「能拿到的都拿到」而不是「某个失败整体卡住」。
 * - 不抄瞬时 UI 态：见 `settingsAuditExports.ts` 顶部 JSDoc。
 */

import { useCallback, useMemo, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import {
  combineAuditOutputs,
  SETTINGS_AUDIT_SECTIONS,
  useAuditSectionStates,
  type AuditSectionStatus,
} from './settingsAuditExports';
import { SETTINGS_TABS, type SettingsTabKey } from './settingsTabs';

/** 单行按钮：文本复制到剪贴板，短暂显示「已复制」反馈。 */
function useCopyFeedback(timeoutMs = 1500) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard?.writeText(text);
      } catch {
        /* 剪贴板权限 / 非安全上下文：静默降级，按钮态回到「复制」。 */
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), timeoutMs);
    },
    [timeoutMs],
  );
  return { copied, copy };
}

/** 单 section 的状态徽章：idle / loading / ready / error 各一种视觉。 */
function StatusBadge({ status }: { status: AuditSectionStatus }) {
  const { t } = useI18n();
  switch (status.kind) {
    case 'loading':
      return (
        <span className="px-1.5 py-0.5 text-ui-2xs rounded bg-primary/10 text-primary">
          {t('settings.audit.loading')}
        </span>
      );
    case 'ready':
      return (
        <span className="px-1.5 py-0.5 text-ui-2xs rounded bg-success/10 text-success">
          {t('settings.audit.ready')}
        </span>
      );
    case 'error':
      return (
        <span
          className="px-1.5 py-0.5 text-ui-2xs rounded bg-danger/10 text-danger"
          title={status.message}
        >
          {t('settings.audit.error')}
        </span>
      );
    default:
      return (
        <span className="px-1.5 py-0.5 text-ui-2xs rounded bg-bg-hover text-muted">
          {t('settings.audit.idle')}
        </span>
      );
  }
}

/** 单个 section 的 row：加载 / 复制摘要 / 复制 JSON 三个原子操作。 */
function SectionRow({
  section,
  status,
  onLoad,
}: {
  section: (typeof SETTINGS_AUDIT_SECTIONS)[number];
  status: AuditSectionStatus;
  onLoad: () => void;
}) {
  const { t } = useI18n();
  const snapshotCopy = useCopyFeedback();
  const jsonCopy = useCopyFeedback();
  const isLoading = status.kind === 'loading';
  const isReady = status.kind === 'ready';
  const snapshot = isReady ? status.payload.snapshot : '';
  const json = isReady ? status.payload.json : '';

  return (
    <div
      data-testid={`audit-section-${section.id}`}
      className="flex items-center justify-between gap-3 py-2 border-b border-border last:border-b-0"
    >
      <div className="flex items-center gap-3 min-w-0">
        <StatusBadge status={status} />
        <span className="text-ui-sm text-text truncate">{t(section.labelKey)}</span>
        {status.kind === 'error' && (
          <span className="text-ui-2xs text-danger truncate" title={status.message}>
            {status.message}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <button
          type="button"
          disabled={isLoading}
          onClick={onLoad}
          className="px-2 py-1 text-ui-2xs rounded border border-border text-text-secondary hover:text-text hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isReady ? t('settings.audit.refresh') : t('settings.audit.load')}
        </button>
        <button
          type="button"
          disabled={!isReady}
          onClick={() => snapshotCopy.copy(snapshot)}
          className="px-2 py-1 text-ui-2xs rounded border border-border text-text-secondary hover:text-text hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {snapshotCopy.copied ? t('settings.audit.copied') : t('settings.audit.copySummary')}
        </button>
        <button
          type="button"
          disabled={!isReady}
          onClick={() => jsonCopy.copy(json)}
          className="px-2 py-1 text-ui-2xs rounded border border-border text-text-secondary hover:text-text hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {jsonCopy.copied ? t('settings.audit.copied') : t('settings.audit.copyJson')}
        </button>
      </div>
    </div>
  );
}

export function AuditExportTab() {
  const { t } = useI18n();
  const { get, load, loadAll } = useAuditSectionStates();
  const allCopySnapshot = useCopyFeedback();
  const allCopyJson = useCopyFeedback();

  // 按 tab 分组展示 —— 与左侧导航分组一致，用户能快速对应到某个 tab。
  const grouped = useMemo(() => {
    const map = new Map<SettingsTabKey, (typeof SETTINGS_AUDIT_SECTIONS)[number][]>();
    for (const section of SETTINGS_AUDIT_SECTIONS) {
      const list = map.get(section.tab) ?? [];
      list.push(section);
      map.set(section.tab, list);
    }
    return Array.from(map.entries());
  }, []);

  const tabLabel = useCallback(
    (key: SettingsTabKey) =>
      SETTINGS_TABS.find((tab) => tab.key === key)?.labelKey
        ? t(SETTINGS_TABS.find((tab) => tab.key === key)!.labelKey)
        : key,
    [t],
  );

  const readyCount = SETTINGS_AUDIT_SECTIONS.filter((s) => get(s.id).kind === 'ready').length;
  const totalCount = SETTINGS_AUDIT_SECTIONS.length;

  const handleCopyAllSnapshot = useCallback(async () => {
    const text = combineAuditOutputs(
      SETTINGS_AUDIT_SECTIONS,
      get,
      'snapshot',
      t('settings.audit.empty'),
    );
    await allCopySnapshot.copy(text);
  }, [get, allCopySnapshot, t]);

  const handleCopyAllJson = useCallback(async () => {
    const text = combineAuditOutputs(SETTINGS_AUDIT_SECTIONS, get, 'json', '{}');
    await allCopyJson.copy(text);
  }, [get, allCopyJson]);

  return (
    <div className="space-y-6">
      <section>
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-ui-lg font-semibold text-text">{t('settings.audit.title')}</h2>
            <p className="text-ui-sm text-text-secondary mt-1">{t('settings.audit.desc')}</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-ui-2xs text-muted">
              {readyCount} / {totalCount}
            </span>
            <button
              type="button"
              onClick={() => void loadAll()}
              className="px-3 py-1.5 text-ui-xs rounded border border-border text-text hover:bg-bg-hover"
            >
              {t('settings.audit.loadAll')}
            </button>
          </div>
        </div>

        <div className="rounded-md border border-border divide-y divide-border">
          {/* 顶部「复制全部」区 */}
          <div className="flex items-center justify-between gap-3 p-3 bg-bg-muted">
            <span className="text-ui-sm text-text">
              {t('settings.audit.copyAll').replace('{count}', String(readyCount))}
            </span>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                disabled={readyCount === 0}
                onClick={() => void handleCopyAllSnapshot()}
                className="px-2 py-1 text-ui-2xs rounded border border-border text-text-secondary hover:text-text hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {allCopySnapshot.copied
                  ? t('settings.audit.copied')
                  : t('settings.audit.copyAllSummary')}
              </button>
              <button
                type="button"
                disabled={readyCount === 0}
                onClick={() => void handleCopyAllJson()}
                className="px-2 py-1 text-ui-2xs rounded border border-border text-text-secondary hover:text-text hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {allCopyJson.copied ? t('settings.audit.copied') : t('settings.audit.copyAllJson')}
              </button>
            </div>
          </div>

          {/* 每个 tab 一簇，每 section 一行 */}
          {grouped.map(([tabKey, sections]) => (
            <div key={tabKey} className="p-3">
              <div className="text-ui-xs font-medium text-muted mb-2 uppercase tracking-wide">
                {tabLabel(tabKey)}
              </div>
              <div>
                {sections.map((section) => (
                  <SectionRow
                    key={section.id}
                    section={section}
                    status={get(section.id)}
                    onLoad={() => void load(section)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
