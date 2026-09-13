// src/widgets/chat/RightPanelToggle.tsx
import { PanelRight } from 'lucide-react';

import { Tooltip } from '../../shared/ui';

interface RightPanelToggleProps {
  open: boolean;
  onClick: () => void;
}

export function RightPanelToggle({ open, onClick }: RightPanelToggleProps) {
  return (
    // P1: 统一 Tooltip（radix）替代原生 title；快捷键提示与 P1-6 的
    // Ctrl/Cmd+Shift+P 切换对应。
    <Tooltip content={open ? '关闭右侧面板 (Ctrl+Shift+P)' : '打开右侧面板 (Ctrl+Shift+P)'} side="bottom">
      <button
        className={
          'p-1.5 rounded hover:bg-bg-hover text-text-secondary transition-colors ' +
          (open ? 'bg-bg-hover' : '')
        }
        onClick={onClick}
        aria-label="切换右侧面板"
      >
        <PanelRight className="w-4 h-4" />
      </button>
    </Tooltip>
  );
}
