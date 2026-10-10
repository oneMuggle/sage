// src/widgets/session/ForkTreeModal.tsx
//
// W2（主流对标）：会话分叉家族树对话框。
// 侧栏会话项的 fork 徽标点击呼出；展示当前会话所在家族的全部分支
// （根 → 各代分叉，同层按创建时间排序），点击任一节点切换到该会话。
// 数据自给：打开时经 sessionApi.list() 拉全量会话（侧栏列表可能被
// 搜索过滤/虚拟化截断，不能复用）。

import { GitBranch } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { sessionApi } from '../../shared/api/sessionApi';
import type { Session } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';
import { Modal } from '../../shared/ui/Modal';

import { buildForkFamily } from './forkTree';

export interface ForkTreeModalProps {
  isOpen: boolean;
  /** 家族树锚定的会话（徽标所在的会话项） */
  session: Session;
  /** 当前激活会话 id（高亮用；可能与锚定会话不同） */
  activeSessionId?: string | null;
  onClose: () => void;
  /** 点击树节点切换会话 */
  onSwitch: (sessionId: string) => void;
}

export function ForkTreeModal({
  isOpen,
  session,
  activeSessionId,
  onClose,
  onSwitch,
}: ForkTreeModalProps) {
  const { t } = useI18n();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setError('');
    sessionApi
      .list()
      .then((list) => {
        if (!cancelled) setSessions(list);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const family = useMemo(() => {
    if (!sessions) return null;
    return buildForkFamily(sessions, session.id);
  }, [sessions, session.id]);

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t('session.fork_tree_title')}>
      <div className="space-y-1 text-sm min-h-[8rem]" data-testid="fork-tree-modal">
        {error && (
          <p className="text-xs text-red-500" data-testid="fork-tree-error">
            {error}
          </p>
        )}
        {!error && family === null && (
          <p className="text-xs text-text-muted" data-testid="fork-tree-loading">
            {t('session.fork_tree_loading')}
          </p>
        )}
        {!error &&
          family !== null &&
          family.map(({ session: s, depth }) => {
            const isCurrent = s.id === session.id;
            const isActive = s.id === activeSessionId;
            return (
              <button
                key={s.id}
                onClick={() => {
                  onSwitch(s.id);
                  onClose();
                }}
                disabled={isActive}
                data-testid={`fork-tree-node-${s.id}`}
                className={`w-full text-left rounded px-2 py-1.5 hover:bg-bg-hover disabled:cursor-default ${
                  isActive ? 'bg-primary/10' : ''
                }`}
                style={{ paddingLeft: `${0.5 + depth * 1.25}rem` }}
              >
                <span className="flex items-center gap-2 min-w-0">
                  {depth > 0 && <GitBranch className="w-3 h-3 text-muted flex-shrink-0" />}
                  <span
                    className={`truncate text-sm ${isCurrent ? 'font-semibold text-primary' : ''}`}
                  >
                    {s.title}
                  </span>
                  {isCurrent && (
                    <span
                      className="text-ui-xs px-1 rounded bg-bg-subtle border border-border text-text-secondary flex-shrink-0"
                      data-testid="fork-tree-current-badge"
                    >
                      {t('session.fork_tree_current')}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-text-muted flex-shrink-0">
                    {new Date(s.created_at).toLocaleString()}
                  </span>
                </span>
              </button>
            );
          })}
        {!error && family !== null && family.length <= 1 && (
          <p className="text-xs text-text-muted" data-testid="fork-tree-single">
            {t('session.fork_tree_single')}
          </p>
        )}
      </div>
    </Modal>
  );
}
