import { useCallback, useEffect, useMemo, useState } from 'react';

import { sessionApi } from '../../../shared/api/sessionApi';
import { workspaceApi } from '../../../shared/api/workspaceApi';
import type { WorkspaceCheckpoint } from '../../../shared/api/workspaceApi';
import { useI18n } from '../../../shared/lib/i18n';
import { Modal } from '../../../shared/ui/Modal';

/**
 * W1（主流对标）：消息级「回滚到此处」对话框。
 *
 * 组装两座现成原语（对标 Claude Code /rewind、Cursor Checkpoints）：
 * - 对话回滚 = `session_fork`（原会话保留，与编辑重发同一非破坏语义）
 * - 文件回滚 = 工作区检查点恢复（默认选中「消息时刻之前」最近的快照）
 *
 * 执行顺序：先恢复文件、后分叉对话——文件恢复失败时中止并报错，
 * 用户可改选「仅对话」。时间匹配用快照 created_at（本地时区字符串）
 * 与消息 created_at（epoch ms）比较，同机场景下足够；列表明示快照
 * 时间供人工确认。
 */

export interface RewindDialogProps {
  isOpen: boolean;
  sessionId: string;
  messageId: string;
  /** 目标消息的 epoch ms 时间戳（快照联动的时间锚点）。 */
  messageCreatedAt: number;
  onClose: () => void;
  /** 分叉成功后回调（携带新会话 id），由调用方切换会话。 */
  onForked: (forkedSessionId: string) => void;
}

type RewindScope = 'both' | 'conversation';

function parseCheckpointTime(createdAt: string): number {
  const parsed = Date.parse(createdAt);
  return Number.isNaN(parsed) ? Number.NEGATIVE_INFINITY : parsed;
}

export function RewindDialog({
  isOpen,
  sessionId,
  messageId,
  messageCreatedAt,
  onClose,
  onForked,
}: RewindDialogProps) {
  const { t } = useI18n();
  const [checkpoints, setCheckpoints] = useState<WorkspaceCheckpoint[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [scope, setScope] = useState<RewindScope>('conversation');
  const [selectedId, setSelectedId] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // 快照列表（新→旧）+「不晚于消息时刻」的合格集合
  const sorted = useMemo(
    () => [...checkpoints].sort((a, b) => parseCheckpointTime(b.createdAt) - parseCheckpointTime(a.createdAt)),
    [checkpoints],
  );
  const qualified = useMemo(
    () => sorted.filter((c) => parseCheckpointTime(c.createdAt) <= messageCreatedAt),
    [sorted, messageCreatedAt],
  );
  const hasQualified = qualified.length > 0;

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setLoaded(false);
    setError('');
    workspaceApi
      .listCheckpoints(sessionId)
      .then((list) => {
        if (cancelled) return;
        setCheckpoints(list);
      })
      .catch(() => {
        if (cancelled) return;
        setCheckpoints([]);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, sessionId]);

  // 合格集合变化时归一默认选择：默认「对话+文件」+ 最近合格快照
  useEffect(() => {
    if (!loaded) return;
    if (hasQualified) {
      setScope('both');
      setSelectedId(qualified[0].checkpointId);
    } else {
      setScope('conversation');
      setSelectedId('');
    }
  }, [loaded, hasQualified, qualified]);

  const handleConfirm = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      if (scope === 'both') {
        const target = qualified.find((c) => c.checkpointId === selectedId) ?? qualified[0];
        if (!target) {
          setScope('conversation');
        } else {
          try {
            await workspaceApi.restoreCheckpoint(sessionId, target.checkpointId);
          } catch (e) {
            setError(
              t('chat.rewind_restore_failed').replace(
                '{message}',
                e instanceof Error ? e.message : String(e),
              ),
            );
            setBusy(false);
            return;
          }
        }
      }
      const forked = await sessionApi.fork(sessionId, messageId);
      onForked(forked.id);
    } catch (e) {
      setError(
        t('chat.rewind_fork_failed').replace(
          '{message}',
          e instanceof Error ? e.message : String(e),
        ),
      );
    } finally {
      setBusy(false);
    }
  }, [scope, qualified, selectedId, sessionId, messageId, onForked, t]);

  return (
    <Modal isOpen={isOpen} onClose={busy ? () => {} : onClose} title={t('chat.rewind_title')}>
      <div className="space-y-3 text-sm" data-testid="rewind-dialog">
        <div>
          <p className="font-medium mb-1">{t('chat.rewind_scope')}</p>
          <label className="flex items-center gap-2" data-testid="rewind-scope-both">
            <input
              type="radio"
              name="rewind-scope"
              checked={scope === 'both'}
              disabled={!hasQualified || busy}
              onChange={() => setScope('both')}
            />
            <span className={!hasQualified ? 'opacity-50' : ''}>{t('chat.rewind_scope_both')}</span>
          </label>
          <label className="flex items-center gap-2" data-testid="rewind-scope-conversation">
            <input
              type="radio"
              name="rewind-scope"
              checked={scope === 'conversation'}
              disabled={busy}
              onChange={() => setScope('conversation')}
            />
            <span>{t('chat.rewind_scope_conversation')}</span>
          </label>
        </div>

        <div>
          <p className="font-medium mb-1">{t('chat.rewind_snapshots')}</p>
          {!loaded ? (
            <p className="text-xs text-text-muted">{t('chat.rewind_loading')}</p>
          ) : !hasQualified ? (
            <p className="text-xs text-text-muted" data-testid="rewind-no-snapshots">
              {t('chat.rewind_no_snapshots')}
            </p>
          ) : (
            <ul className="max-h-48 overflow-auto space-y-1">
              {qualified.map((c) => (
                <li key={c.checkpointId}>
                  <label className="flex items-center gap-2" data-testid={`rewind-checkpoint-${c.checkpointId}`}>
                    <input
                      type="radio"
                      name="rewind-checkpoint"
                      checked={scope === 'both' && selectedId === c.checkpointId}
                      disabled={busy}
                      onChange={() => {
                        setScope('both');
                        setSelectedId(c.checkpointId);
                      }}
                    />
                    <span className="text-xs">
                      {new Date(c.createdAt).toLocaleString()} ·{' '}
                      {t('chat.rewind_files_count').replace('{count}', String(c.files ?? 0))}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>

        {error && (
          <p className="text-xs text-red-500" data-testid="rewind-error">
            {error}
          </p>
        )}
        <p className="text-xs text-text-muted">{t('chat.rewind_hint')}</p>
      </div>

      <div className="mt-4 flex justify-end gap-2" data-testid="rewind-actions">
        <button
          className="px-3 py-1.5 text-sm rounded border border-border hover:bg-bg-hover disabled:opacity-50"
          onClick={onClose}
          disabled={busy}
          data-testid="rewind-cancel"
        >
          {t('common.cancel')}
        </button>
        <button
          className="px-3 py-1.5 text-sm rounded bg-primary text-white hover:opacity-90 disabled:opacity-50"
          onClick={handleConfirm}
          disabled={busy || (scope === 'both' && (!loaded || !hasQualified))}
          data-testid="rewind-confirm"
        >
          {t('chat.rewind_confirm')}
        </button>
      </div>
    </Modal>
  );
}
