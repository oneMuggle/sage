// src/widgets/chat/RightPanelToggle.tsx
import { PanelRight } from 'lucide-react';

import { Tooltip } from '../../shared/ui';

interface RightPanelToggleProps {
  open: boolean;
  onClick: () => void;
  /** right-panel R1 批次 B: 面板关着时的未读产物数 —— >0 渲染红点（对齐 Claude） */
  unseenCount?: number;
}

export function RightPanelToggle({ open, onClick, unseenCount = 0 }: RightPanelToggleProps) {
  const showDot = !open && unseenCount > 0;
  return (
    // P1: 统一 Tooltip（radix）替代原生 title；快捷键提示与 P1-6 的
    // Ctrl/Cmd+Shift+P 切换对应。
    <Tooltip
      content={
        showDot
          ? `右侧面板 · ${unseenCount} 个新产物 (Ctrl+Shift+P)`
          : open
            ? '关闭右侧面板 (Ctrl+Shift+P)'
            : '打开右侧面板 (Ctrl+Shift+P)'
      }
      side="bottom"
    >
      <button
        className={
          'relative p-1.5 rounded hover:bg-bg-hover text-text-secondary transition-colors ' +
          (open ? 'bg-bg-hover' : '')
        }
        onClick={onClick}
        aria-label="切换右侧面板"
        data-testid="right-panel-toggle"
      >
        <PanelRight className="w-4 h-4" />
        {showDot && (
          <span
            className="absolute top-1 right-1 w-2 h-2 rounded-full bg-error border border-surface"
            data-testid="right-panel-unseen-dot"
            aria-hidden
          />
        )}
      </button>
    </Tooltip>
  );
}

export interface RightPanelToggleAuditInput {
  isOpen: boolean;
  activeTab: string;
  badgeCount: number;
  shortcutConfigured: boolean;
}

export interface RightPanelToggleAuditReport {
  isOpen: boolean;
  activeTab: string;
  badgeCount: number;
  shortcutConfigured: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateRightPanelToggleAudit(
  input: RightPanelToggleAuditInput,
): RightPanelToggleAuditReport {
  const activeTab = input.activeTab.trim();
  const badgeCount = Math.max(0, Math.trunc(input.badgeCount));
  const issueCodes: string[] = [];

  if (!activeTab) {
    issueCodes.push('missing_right_panel_active_tab');
  }
  if (input.badgeCount < 0) {
    issueCodes.push('negative_badge_count');
  }
  if (!input.shortcutConfigured) {
    issueCodes.push('missing_toggle_shortcut');
  }

  return {
    isOpen: Boolean(input.isOpen),
    activeTab,
    badgeCount,
    shortcutConfigured: Boolean(input.shortcutConfigured),
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportRightPanelToggleAuditJson(
  input: RightPanelToggleAuditInput,
): string {
  return JSON.stringify(evaluateRightPanelToggleAudit(input));
}
