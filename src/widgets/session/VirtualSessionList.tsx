import { useVirtualizer } from '@tanstack/react-virtual';
import { useMemo, useRef } from 'react';

import type { Session } from '../../shared/lib/store';

import { SessionItem } from './SessionItem';

/** 根据时间将消息分组为: 今天/昨天/本周/更早 */
function getSessionGroup(timestamp: number): string {
  const now = new Date();
  const date = new Date(timestamp);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekStart = new Date(today.getTime() - today.getDay() * 86400000);

  if (date >= today) return '今天';
  if (date >= yesterday) return '昨天';
  if (date >= weekStart) return '本周';
  return '更早';
}

interface GroupedSession {
  type: 'group';
  label: string;
}

interface FlatSession {
  type: 'session';
  session: Session;
}

type ListItem = GroupedSession | FlatSession;

interface VirtualSessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  maxHeight?: string;
  /** P1: 重命名回调(与 SessionList 参数对齐,虚拟化分支功能不缩水) */
  onRename?: (sessionId: string, title: string) => Promise<void>;
  /** P1: F12 消息内容命中计数(会话 id → 命中条数;缺省不显示徽标) */
  messageHitsBySession?: Map<string, number>;
}

/**
 * 虚拟化会话列表。超阈值（>120 条）时启用，仅做渲染分组（按时间分桶）。
 * 排序由后端 SQL 完成，前端不再传入 order 也不再做二次排序。
 */
export function VirtualSessionList({
  sessions,
  currentSessionId,
  onSelect,
  onDelete,
  maxHeight = 'calc(100vh - 320px)',
  onRename,
  messageHitsBySession,
}: VirtualSessionListProps) {
  const parentRef = useRef<HTMLDivElement>(null);

  // 直接使用后端返回的顺序；二次排序（pin/时间）已在 SQL 层完成。
  const sorted = useMemo(() => sessions, [sessions]);

  // 构建扁平列表 (含分组头)
  const items: ListItem[] = [];
  let lastGroup = '';

  for (const session of sorted) {
    const ts = session.last_message_at ?? session.updated_at;
    const group = getSessionGroup(ts);
    if (group !== lastGroup) {
      items.push({ type: 'group', label: group });
      lastGroup = group;
    }
    items.push({ type: 'session', session });
  }

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => (items[index].type === 'group' ? 28 : 52),
    overscan: 5,
  });

  if (items.length === 0) {
    return <div className="px-3 py-4 text-xs text-text-muted text-center">暂无对话记录</div>;
  }

  return (
    <div ref={parentRef} className="overflow-y-auto" style={{ maxHeight, minHeight: 0 }}>
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const item = items[virtualRow.index];

          if (item.type === 'group') {
            return (
              <div
                key={`group-${item.label}`}
                className="text-ui-2xs font-semibold uppercase tracking-wide text-muted px-3 py-1 sticky top-0 bg-surface"
                style={{
                  position: 'absolute',
                  top: virtualRow.start,
                  left: 0,
                  width: '100%',
                  height: `${virtualRow.size}px`,
                }}
              >
                {item.label}
              </div>
            );
          }

          return (
            <div
              key={item.session.id}
              style={{
                position: 'absolute',
                top: virtualRow.start,
                left: 0,
                width: '100%',
                height: `${virtualRow.size}px`,
              }}
            >
              <SessionItem
                session={item.session}
                isActive={item.session.id === currentSessionId}
                onSelect={() => onSelect(item.session.id)}
                onDelete={() => onDelete(item.session.id)}
                onRename={onRename}
                messageHits={messageHitsBySession?.get(item.session.id)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export interface VirtualSessionListAuditInput {
  totalSessionCount: number;
  renderedRowCount: number;
  rowHeightPx: number;
  overscanCount: number;
}

export interface VirtualSessionListAuditReport {
  totalSessionCount: number;
  renderedRowCount: number;
  virtualizationRatio: number;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateVirtualSessionListGovernanceAudit(
  input: VirtualSessionListAuditInput,
): VirtualSessionListAuditReport {
  const issueCodes: string[] = [];
  const totalSessionCount = Math.max(0, Math.trunc(input.totalSessionCount));
  const renderedRowCount = Math.max(0, Math.trunc(input.renderedRowCount));
  if (input.rowHeightPx < 24 || input.rowHeightPx > 160) {
    issueCodes.push('VIRTUAL_SESSION_LIST_ROW_HEIGHT_INVALID');
  }
  if (input.overscanCount < 0 || input.overscanCount > 50) {
    issueCodes.push('VIRTUAL_SESSION_LIST_OVERSCAN_OUT_OF_RANGE');
  }
  if (totalSessionCount > 0 && renderedRowCount > totalSessionCount + Math.max(0, input.overscanCount) * 2) {
    issueCodes.push('VIRTUAL_SESSION_LIST_RENDER_OVERFLOW');
  }
  const virtualizationRatio =
    totalSessionCount > 0 ? Number((renderedRowCount / totalSessionCount).toFixed(4)) : 1;
  return {
    totalSessionCount,
    renderedRowCount,
    virtualizationRatio,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
