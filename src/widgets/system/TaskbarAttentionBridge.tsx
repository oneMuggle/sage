// src/widgets/system/TaskbarAttentionBridge.tsx
//
// 2026-11-05: 把「等待审批/提问」的注意力计数推给 Electron 主进程，
// 由主进程驱动任务栏闪烁 / macOS dock badge（窗口聚焦时自动清除）。
// 只做单向同步；renderer 不持有任何主进程状态。

import { useEffect } from 'react';

import { useAttentionSnapshot } from '../../features/attention/useAttentionSnapshot';

export function TaskbarAttentionBridge(): null {
  const attention = useAttentionSnapshot();
  const awaitingApproval = attention.entries
    .filter((entry) => entry.kind === 'approval' || entry.kind === 'question')
    .reduce((sum, entry) => sum + entry.count, 0);

  useEffect(() => {
    window.electronAPI?.setTaskbarAttention?.({ awaitingApproval }).catch(() => undefined);
  }, [awaitingApproval]);

  return null;
}
