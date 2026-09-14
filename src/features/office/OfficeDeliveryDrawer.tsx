// src/features/office/OfficeDeliveryDrawer.tsx
/**
 * A4b: office 交付包抽屉 —— word 生成成功后的验收视图：
 * ① lint 段（formatSpec 存在时调 officeApi.lintWord：ok 徽章 +
 *    error/warning 计数 + issues Top N；无 spec 时如实展示跳过；
 *    失败可重试，不阻塞决议）；
 * ② 预览段（OfficePreviewPanel 嵌入，数据经 officeApi.readWord 回读）；
 * ③ 决议区：接受 = completeTask 归档；打回 = completeTask(cancelled) +
 *    跳 Office 页。
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { officeApi } from '../../shared/api/officeApi';
import type { OfficeWordLintResult, WordFormatSpec } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';
import { useTaskCenterStore } from '../task-center/taskCenterStore';

import { OfficePreviewPanel, type OfficePreviewData } from './OfficePreviewPanel';

/** 交付包内最多展开的 issue 条数，超出只记数。 */
const ISSUES_DISPLAY_CAP = 10;

type LintState = 'loading' | 'ready' | 'skipped' | 'error';

export interface OfficeDeliveryDrawerProps {
  /** 任务中心条目 id（决议写回 completeTask 用）。 */
  entryId: string;
  workspacePath: string;
  filePath: string;
  /** 生成时携带的格式规范；null = 无规范，lint 段展示跳过。 */
  formatSpec: WordFormatSpec | null;
  /** 受控可见性（调用方通常接 taskCenterStore.delivery）。 */
  open: boolean;
  /** 请求关闭。 */
  onClose: () => void;
}

export function OfficeDeliveryDrawer({
  entryId,
  workspacePath,
  filePath,
  formatSpec,
  open,
  onClose,
}: OfficeDeliveryDrawerProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const entry = useTaskCenterStore((s) => s.tasks[entryId]);
  const completeTask = useTaskCenterStore((s) => s.completeTask);
  const [lint, setLint] = useState<OfficeWordLintResult | null>(null);
  const [lintState, setLintState] = useState<LintState>('loading');
  const [lintSeq, setLintSeq] = useState(0);
  const [preview, setPreview] = useState<OfficePreviewData | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (!formatSpec) {
      setLintState('skipped');
      setLint(null);
      return;
    }
    let cancelled = false;
    setLintState('loading');
    officeApi
      .lintWord({ workspace_path: workspacePath, file_path: filePath, format_spec: formatSpec })
      .then((result) => {
        if (cancelled) return;
        setLint(result);
        setLintState('ready');
      })
      .catch(() => {
        if (!cancelled) {
          setLint(null);
          setLintState('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, workspacePath, filePath, formatSpec, lintSeq]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setPreview(null);
    setPreviewFailed(false);
    officeApi
      .readWord({ workspace_path: workspacePath, file_path: filePath })
      .then((data) => {
        if (cancelled) return;
        setPreview({ docType: 'word', data });
      })
      .catch(() => {
        if (!cancelled) setPreviewFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open, workspacePath, filePath]);

  if (!open || !entry) {
    return null;
  }

  const decided = entry.status === 'succeeded' || entry.status === 'cancelled';

  const handleAccept = () => {
    completeTask(entryId, 'succeeded');
  };

  const handleReject = () => {
    completeTask(entryId, 'cancelled');
    onClose();
    navigate('/office');
  };

  return (
    <div
      className="fixed inset-y-0 right-0 w-96 bg-bg-primary border-l border-border-primary shadow-lg z-50 flex flex-col"
      data-testid="office-delivery-drawer"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-primary">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium truncate">{t('office.delivery.title')}</span>
          {decided ? (
            <span className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 shrink-0">
              {t('office.delivery.archived')}
            </span>
          ) : (
            <span className="text-xs px-2 py-0.5 rounded bg-yellow-100 text-yellow-800 shrink-0">
              {t('office.delivery.awaiting')}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-text-tertiary hover:text-text-primary"
          data-testid="drawer-close"
          aria-label={t('office.delivery.close')}
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Lint section */}
        <div className="px-4 py-3 border-b border-border-primary">
          <div className="text-xs text-text-tertiary mb-2">{t('office.delivery.lint')}</div>
          {lintState === 'loading' && (
            <div className="text-xs text-text-tertiary">{t('orchestration.loading')}</div>
          )}
          {lintState === 'skipped' && (
            <div className="text-xs text-text-tertiary" data-testid="lint-skipped">
              {t('office.delivery.lintSkipped')}
            </div>
          )}
          {lintState === 'error' && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-red-600">{t('office.delivery.lintFailed')}</span>
              <button
                type="button"
                onClick={() => setLintSeq((n) => n + 1)}
                className="text-xs text-primary hover:underline"
                data-testid="lint-retry"
              >
                {t('office.delivery.retry')}
              </button>
            </div>
          )}
          {lintState === 'ready' && lint && (
            <div data-testid="lint-result">
              <div className="flex items-center gap-2 mb-2">
                {lint.ok ? (
                  <span className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
                    {t('office.delivery.lintPass')}
                  </span>
                ) : (
                  <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-800">
                    {t('office.delivery.lintFail')}
                  </span>
                )}
                <span className="text-xs text-text-secondary">
                  {t('office.delivery.errors').replace('{n}', String(lint.error_count))}
                  {' · '}
                  {t('office.delivery.warnings').replace('{n}', String(lint.warning_count))}
                </span>
              </div>
              <div className="text-xs text-text-tertiary mb-1">
                {t('office.delivery.rulesChecked').replace('{n}', String(lint.checked_rules.length))}
              </div>
              {lint.issues.length > 0 && (
                <ul className="space-y-1" data-testid="lint-issues">
                  {lint.issues.slice(0, ISSUES_DISPLAY_CAP).map((issue) => (
                    <li key={`${issue.rule_id}-${issue.message}`} className="text-xs">
                      <span
                        className={
                          issue.severity === 'error' ? 'text-red-600 font-medium' : 'text-yellow-700 font-medium'
                        }
                      >
                        [{issue.rule_id}]
                      </span>{' '}
                      <span className="text-text-secondary">{issue.message}</span>
                      {issue.fix_hint !== '' && (
                        <span className="text-text-tertiary truncate block" title={issue.fix_hint}>
                          {issue.fix_hint}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {lint.issues.length > ISSUES_DISPLAY_CAP && (
                <div className="text-xs text-text-tertiary mt-1">
                  {t('office.delivery.moreIssues').replace(
                    '{n}',
                    String(lint.issues.length - ISSUES_DISPLAY_CAP),
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Preview section */}
        <div className="px-4 py-3 border-b border-border-primary">
          <div className="text-xs text-text-tertiary mb-2">{t('office.delivery.preview')}</div>
          {previewFailed ? (
            <div className="text-xs text-text-tertiary" data-testid="preview-failed">
              {t('office.delivery.previewFailed')}
            </div>
          ) : (
            <div data-testid="delivery-preview">
              <OfficePreviewPanel preview={preview} workspacePath={workspacePath} />
            </div>
          )}
        </div>

        {/* File meta */}
        <div className="px-4 py-3 text-xs text-text-secondary">
          <div className="font-mono truncate" title={filePath}>
            {filePath}
          </div>
        </div>
      </div>

      {/* Decision zone */}
      {!decided && (
        <div className="px-4 py-3 border-t border-border-primary" data-testid="decision-zone">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleAccept}
              className="flex-1 text-sm px-3 py-1.5 rounded bg-primary text-white hover:opacity-90"
              data-testid="decision-accept"
            >
              {t('office.delivery.accept')}
            </button>
            <button
              type="button"
              onClick={handleReject}
              className="flex-1 text-sm px-3 py-1.5 rounded border border-red-300 text-red-600 hover:bg-red-50"
              data-testid="decision-reject"
            >
              {t('office.delivery.reject')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
