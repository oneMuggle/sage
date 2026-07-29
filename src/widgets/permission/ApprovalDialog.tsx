/**
 * ApprovalDialog — M1 工具安全加固的全局审批模态框。
 *
 * 当 `usePermissionState.currentRequest` 非空时渲染（由 useChat 消费
 * `state: 'permission_request'` 流事件写入 store）。用户点「允许/拒绝」
 * → `invoke('permissions_answer', {requestId, approved, remember})`
 * → 无论成败都 resolve() 关闭对话框：
 *
 *   - ok=false（unknown_or_expired / permission_gate_not_initialized）
 *     说明后端 gate 已自行超时 fail-closed，agent 已带着「权限拒绝」
 *     继续跑，UI 侧无需卡住。
 *   - invoke 抛错（IPC/HTTP 故障）同理：后端 300s 后 default-deny，
 *     对话框一直挂着只会误导用户。
 *
 * 错误通过 sonner toast 暴露（与项目其它 widget 一致）。
 */
import { ShieldAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { usePermissionState } from '../../entities/permission/permissionState';
import type { PermissionRequest } from '../../shared/api';
import { invoke } from '../../shared/api/desktopInvoke';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

/** permissions_answer 应答体（HTTP 恒 200，ok 字段区分成败） */
interface AnswerResponse {
  ok: boolean;
  error?: string;
}

/** 风险分级 → 徽章配色（destructive=red / suspicious=amber / safe=neutral） */
const RISK_BADGE_CLASSES: Readonly<Record<PermissionRequest['risk'], string>> = {
  safe: 'border-border bg-bg-muted text-text-secondary',
  suspicious: 'border-warning/40 bg-warning/10 text-warning',
  destructive: 'border-error/40 bg-error/10 text-error',
};

const RISK_LABEL_KEYS: Readonly<Record<PermissionRequest['risk'], TranslationKey>> = {
  safe: 'permission.risk.safe',
  suspicious: 'permission.risk.suspicious',
  destructive: 'permission.risk.destructive',
};

export function ApprovalDialog() {
  const { t } = useI18n();
  const currentRequest = usePermissionState((s) => s.currentRequest);
  const resolve = usePermissionState((s) => s.resolve);
  const [remember, setRemember] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // 新请求到达时重置上一个请求遗留的勾选/提交状态（store 直接替换
  // currentRequest，组件不卸载，必须显式重置局部 state）
  const requestId = currentRequest?.request_id ?? null;
  useEffect(() => {
    setRemember(false);
    setSubmitting(false);
  }, [requestId]);

  if (!currentRequest) return null;

  const risk = RISK_BADGE_CLASSES[currentRequest.risk] ? currentRequest.risk : ('safe' as const);

  const answer = async (approved: boolean): Promise<void> => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const resp = await invoke<AnswerResponse>('permissions_answer', {
        requestId: currentRequest.request_id,
        approved,
        remember,
      });
      if (!resp || resp.ok !== true) {
        toast.error(`${t('permission.toast.failed')}: ${resp?.error ?? 'unknown'}`);
      }
    } catch (err) {
      toast.error(
        `${t('permission.toast.failed')}: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      // 无论 ok/error 都关闭 — 理由见文件头注
      resolve();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      role="presentation"
      onKeyDown={(e) => {
        // Escape = 拒绝（显式决定，不做静默关闭；后端 fail-closed 语义一致）
        if (e.key === 'Escape') void answer(false);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('permission.title')}
        data-testid="permission-approval-dialog"
        className="bg-surface border border-border rounded-lg w-full max-w-md mx-4 p-5 shadow-xl"
      >
        <div className="flex items-center gap-2 mb-3">
          <ShieldAlert className="w-4 h-4 text-warning shrink-0" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text">{t('permission.title')}</h3>
          <span
            data-testid="permission-risk-badge"
            className={`ml-auto px-2 py-0.5 text-xs rounded border ${RISK_BADGE_CLASSES[risk]}`}
          >
            {t(RISK_LABEL_KEYS[risk])}
          </span>
        </div>

        <div className="space-y-3">
          <div className="flex items-baseline gap-2 text-sm">
            <span className="text-text-secondary shrink-0">{t('permission.tool')}</span>
            <code
              data-testid="permission-tool-name"
              className="font-mono text-text bg-bg-muted px-1.5 py-0.5 rounded text-xs"
            >
              {currentRequest.tool_name}
            </code>
          </div>

          <p
            data-testid="permission-message"
            className="text-xs text-text-secondary leading-relaxed"
          >
            {currentRequest.message}
          </p>

          <div>
            <span className="block text-xs text-text-secondary mb-1">{t('permission.args')}</span>
            <pre
              data-testid="permission-args"
              className="text-xs font-mono bg-bg border border-border rounded p-2 max-h-40 overflow-auto whitespace-pre-wrap break-all text-text"
            >
              {currentRequest.args_summary}
            </pre>
          </div>

          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer select-none">
            <input
              type="checkbox"
              data-testid="permission-remember"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="w-3.5 h-3.5 accent-primary"
            />
            {t('permission.remember')}
          </label>

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              data-testid="permission-deny"
              disabled={submitting}
              onClick={() => void answer(false)}
              className="px-3 py-1.5 text-xs border border-border rounded text-text-secondary hover:text-text hover:bg-bg-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t('permission.deny')}
            </button>
            <button
              type="button"
              data-testid="permission-approve"
              disabled={submitting}
              onClick={() => void answer(true)}
              className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t('permission.approve')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
