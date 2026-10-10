// src/shared/ui/PanelShell.tsx
// 通用侧栏/底栏外壳（UX-IA R4 批次 A）。
//
// 抽自 RightPanel.tsx 的 40px 头部 + 可选 tabs + 动作槽 + 左边缘拖拽手柄 + 滚动体 + 空态。
// 后续批次 B（LeftListSlot）与批次 C（RightPanel / DeepResearchProgress /
// ArtifactViewer / PreviewPanel / TerminalPanel）都会复用这份外壳，避免每个面板各自
// 维护一套 36px/40px 头部、各自定义一套关闭按钮热区。
//
// 注意：外壳只管面板「内部结构」，不接管外层容器的开合动画 —— push 与 overlay 的
// 动画语义不同，由各宿主在自身布局层处理（对齐 RightPanel.tsx:466-482 的既有分工）。
import { clsx } from 'clsx';
import type { ReactNode } from 'react';

interface PanelShellTab {
  id: string;
  label: string;
  /** >0 时渲染 "标签 (N)"（批次 C 统一产物/变更计数徽标的呈现） */
  count?: number;
}

interface PanelShellProps {
  /** 无 tabs 时的头部标题 */
  title?: string;
  tabs?: readonly PanelShellTab[];
  activeTab?: string;
  onTabChange?: (tabId: string) => void;
  /**
   * 头部动作区（最大化 / 关闭 / 宽度档位）。
   * 批次 C 会把 chat 右栏那一排（铃铛 + S/M/L + 最大化 + 关闭）收进这里的
   * 溢出菜单 —— 现状 5 个 tab 标签 + 5 个按钮挤在 40px 一行里，热区只有 20px。
   */
  actions?: ReactNode;
  children: ReactNode;
  /** 内容区空态：统一「无内容」的呈现，避免每个面板各写一套 */
  empty?: boolean;
  emptyLabel?: string;
  /** 左边缘拖拽手柄（right / left-list 槽位贴边时用） */
  onResizeMouseDown?: (e: React.MouseEvent) => void;
  onResizeDoubleClick?: () => void;
  onResizeKeyDown?: (e: React.KeyboardEvent) => void;
  testId?: string;
}

// DESIGN.md 密度基线：图标按钮热区下限 28px（批次 C 的 C-2 验收项）。
// 现状 chat 右栏的档位按钮是 w-5（20px）热区，迁移后统一走本组件。
const ACTION_BUTTON_CLASS =
  'inline-flex items-center justify-center h-7 min-w-7 px-1 rounded-radius-sm ' +
  'text-text-secondary hover:text-text hover:bg-bg-hover transition-colors';

export interface PanelShellActionProps {
  /** 无障碍标签 + 原生 title，二者同源，避免又一处只有图标的按钮 */
  label: string;
  onClick?: () => void;
  pressed?: boolean;
  children: ReactNode;
}

/** 面板头部动作按钮：统一 28px 热区 + 必带可访问标签。 */
export function PanelShellAction({ label, onClick, pressed, children }: PanelShellActionProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      className={ACTION_BUTTON_CLASS}
    >
      {children}
    </button>
  );
}

export function PanelShell({
  title,
  tabs,
  activeTab,
  onTabChange,
  actions,
  children,
  empty = false,
  emptyLabel = '暂无内容',
  onResizeMouseDown,
  onResizeDoubleClick,
  onResizeKeyDown,
  testId,
}: PanelShellProps) {
  const showTabs = Boolean(tabs && tabs.length > 0 && onTabChange);

  return (
    <section
      data-testid={testId}
      className="relative h-full flex flex-col min-h-0 overflow-hidden bg-surface border-l border-border"
    >
      {onResizeMouseDown && (
        <div
          className="absolute top-0 left-0 h-full w-1.5 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
          onMouseDown={onResizeMouseDown}
          onDoubleClick={onResizeDoubleClick}
          onKeyDown={onResizeKeyDown}
          role="separator"
          aria-orientation="vertical"
          aria-label="拖拽调整面板宽度（左右方向键微调，双击复位）"
          tabIndex={0}
          data-testid="panel-shell-resize-handle"
        />
      )}

      {(title || showTabs || actions) && (
        <header
          className="h-12 flex items-center border-b border-border px-2 gap-1 flex-shrink-0"
          data-testid="panel-shell-header"
        >
          {showTabs ? (
            <div className="flex items-center flex-1 min-w-0 overflow-x-auto h-full">
              {tabs!.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => onTabChange!(tab.id)}
                  aria-current={activeTab === tab.id}
                  className={clsx(
                    'px-2 h-full text-ui-sm font-medium transition-colors whitespace-nowrap',
                    activeTab === tab.id
                      ? 'text-primary border-b-2 border-primary'
                      : 'text-text-secondary hover:text-text',
                  )}
                  data-testid={`panel-shell-tab-${tab.id}`}
                >
                  {tab.count != null && tab.count > 0 ? `${tab.label} (${tab.count})` : tab.label}
                </button>
              ))}
            </div>
          ) : (
            title && (
              <h2 className="text-ui-sm font-semibold text-text truncate px-1">{title}</h2>
            )
          )}
          {actions && <div className="flex items-center gap-0.5 ml-auto flex-shrink-0">{actions}</div>}
        </header>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto" data-testid="panel-shell-body">
        {empty ? (
          <p className="py-8 text-center text-ui-sm text-text-muted px-4">{emptyLabel}</p>
        ) : (
          children
        )}
      </div>
    </section>
  );
}
