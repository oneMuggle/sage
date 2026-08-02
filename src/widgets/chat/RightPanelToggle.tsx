// src/widgets/chat/RightPanelToggle.tsx
import { PanelRight } from 'lucide-react';

interface RightPanelToggleProps {
  open: boolean;
  onClick: () => void;
}

export function RightPanelToggle({ open, onClick }: RightPanelToggleProps) {
  return (
    <button
      className={
        'p-1.5 rounded hover:bg-bg-hover text-text-secondary transition-colors ' +
        (open ? 'bg-bg-hover' : '')
      }
      onClick={onClick}
      title={open ? '关闭右侧面板' : '打开右侧面板'}
      aria-label="切换右侧面板"
    >
      <PanelRight className="w-4 h-4" />
    </button>
  );
}
