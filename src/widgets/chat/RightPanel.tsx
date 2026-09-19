// src/widgets/chat/RightPanel.tsx
import { Bell, BellOff, Maximize2, Minimize2, X } from 'lucide-react';
import { memo, useEffect, useState } from 'react';

import type { Artifact } from '../../features/artifacts/artifactApi';
import { revealArtifact } from '../../features/artifacts/artifactApi';
import { useArtifacts } from '../../features/artifacts/useArtifacts';
import { useChangesListStore } from '../../features/changes/changesListStore';
import { useConversationOutline } from '../../features/chat/useConversationOutline';
import {
  isArtifactAutoOpenEnabled,
  setArtifactAutoOpenEnabled,
  useRightPanelStore,
  type RightPanelTab,
} from '../../features/right-panel/rightPanelStore';
import type { TaskBoard } from '../../features/send-message/useChat';
import type { ToolCall } from '../../shared/lib/store';
import { useResizablePanel } from '../../shared/lib/useResizablePanel';

import { ConversationOutline } from './ConversationOutline';
import { ArtifactViewer } from './artifacts/ArtifactViewer';
import { ArtifactsSection } from './artifacts/ArtifactsSection';
import { ChangesSection } from './changes/ChangesSection';
import { ProgressSection } from './progress/ProgressSection';

interface RightPanelProps {
  iteration: number;
  streamingState: string | null;
  toolCalls: ToolCall[];
  isLoading: boolean;
  sessionId: string | null;
  taskBoard?: TaskBoard | null; // 新增：编排任务板
  // Wave 3 (2026-08-14): 计划卡接线回调透传。
  // M4 (2026-08-15): onPlanStart 已删。
  // Wave 4 (2026-09-06): onResumeRun 已删 —— 历史编排记录功能移除。
  onCancelExecution?: (runId: string) => void;
  // RV3 (round8): 终态且有失败任务时的重跑入口（透传 ProgressSection → TaskTreeSection）。
  onRerunFailed?: (runId: string) => void;
  // RV4 (round27): 单任务重试入口（失败行内「重试」按钮）。
  onRetryTask?: (runId: string, taskId: string) => void;
  // P1 (UI 优化方案 2026-09-13): push = 参与 flex 挤压主区（Claude
  // artifacts 风格，桌面端）；overlay = fixed 覆盖层（窄屏/移动端回退）。
  variant?: 'overlay' | 'push';
}

const RIGHT_PANEL_TABS: readonly RightPanelTab[] = [
  'progress',
  'outline',
  'changes',
  'artifacts',
];

const TAB_LABELS: Record<RightPanelTab, string> = {
  progress: '进度',
  artifacts: '产物',
  changes: '变更',
  outline: '目录',
};

/** 宽度档位（right-panel R1 批次 D，对齐 Claude 的小/中/大三档） */
const WIDTH_PRESETS = [
  { label: 'S', width: 320 },
  { label: 'M', width: 440 },
  { label: 'L', width: 560 },
] as const;

interface PanelHeaderProps {
  tab?: RightPanelTab;
  onTabChange?: (t: RightPanelTab) => void;
  onClose: () => void;
  /** 批次 D: 最大化/还原（push 模式才提供；overlay 窄屏无意义） */
  maximized?: boolean;
  onToggleMaximize?: () => void;
  /** 批次 D: 当前档位高亮 + 档位应用回调 */
  activePreset?: string | null;
  onApplyPreset?: (width: number) => void;
  /** 当前 Tab 是否为产物（决定是否显示自动唤起开关） */
  showAutoOpenToggle?: boolean;
  /** R2 批次 C: 产物计数徽标（>0 时产物 Tab 显示 "产物 (N)"） */
  artifactCount?: number;
  /** R3 批次 C: 变更计数徽标（>0 时变更 Tab 显示 "变更 (N)"） */
  changesCount?: number;
}

/** 产物自动唤起开关（就地读写 localStorage；事件侧 isArtifactAutoOpenEnabled 同源） */
function AutoOpenToggle() {
  const [enabled, setEnabled] = useState(() => isArtifactAutoOpenEnabled());
  return (
    <button
      className={
        'p-2 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors ' +
        (enabled ? 'text-primary' : '')
      }
      onClick={() => {
        const next = !enabled;
        setArtifactAutoOpenEnabled(next);
        setEnabled(next);
      }}
      title={enabled ? '产物创建时自动展开面板：开' : '产物创建时自动展开面板：关'}
      aria-label="切换产物自动展开"
      data-testid="right-panel-auto-open-toggle"
    >
      {enabled ? <Bell className="w-4 h-4" /> : <BellOff className="w-4 h-4" />}
    </button>
  );
}

export function PanelHeader({
  tab,
  onTabChange,
  onClose,
  maximized,
  onToggleMaximize,
  activePreset,
  onApplyPreset,
  showAutoOpenToggle,
  artifactCount = 0,
  changesCount = 0,
}: PanelHeaderProps) {
  // 宽度档位（三档小按钮；未提供回调时隐藏）
  const presets = onApplyPreset
    ? WIDTH_PRESETS.map((p) => (
        <button
          key={p.label}
          className={
            'w-5 py-0.5 text-[10px] font-medium rounded transition-colors ' +
            (activePreset === p.label
              ? 'bg-primary/15 text-primary'
              : 'text-text-secondary hover:text-text hover:bg-bg-hover')
          }
          onClick={() => onApplyPreset(p.width)}
          title={`面板宽度：${p.label}（${p.width}px）`}
          aria-label={`面板宽度档位 ${p.label}`}
          data-testid={`right-panel-preset-${p.label}`}
        >
          {p.label}
        </button>
      ))
    : null;

  const maximizeButton = onToggleMaximize ? (
    <button
      className="p-2 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
      onClick={onToggleMaximize}
      title={maximized ? '还原面板宽度' : '最大化面板'}
      aria-label={maximized ? '还原面板宽度' : '最大化面板'}
      data-testid="right-panel-maximize-toggle"
    >
      {maximized ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
    </button>
  ) : null;

  const closeButton = (
    <button
      className="p-2 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
      onClick={onClose}
      title="关闭右侧面板"
      aria-label="关闭右侧面板"
    >
      <X className="w-4 h-4" />
    </button>
  );

  // list 视图:Progress / Artifacts tabs + 档位/最大化/× 按钮
  if (tab !== undefined && onTabChange) {
    return (
      <div className="flex border-b border-border items-center pr-1">
        {RIGHT_PANEL_TABS.map((t) => (
          <button
            key={t}
            className={
              'flex-1 min-w-0 py-2 text-sm font-medium transition-colors ' +
              (tab === t
                ? 'text-primary border-b-2 border-primary'
                : 'text-text-secondary hover:text-text')
            }
            onClick={() => onTabChange(t)}
          >
            {t === 'artifacts' && artifactCount > 0
              ? `${TAB_LABELS[t]} (${artifactCount})`
              : t === 'changes' && changesCount > 0
                ? `${TAB_LABELS[t]} (${changesCount})`
                : TAB_LABELS[t]}
          </button>
        ))}
        <div className="flex items-center gap-0.5 ml-1 shrink-0">
          {showAutoOpenToggle && <AutoOpenToggle />}
          {presets}
          {maximizeButton}
          {closeButton}
        </div>
      </div>
    );
  }

  // ArtifactViewer 视图:最大化/× 按钮
  return (
    <div className="flex justify-end border-b border-border items-center h-10 px-2 gap-0.5">
      {maximizeButton}
      {closeButton}
    </div>
  );
}

function RightPanelInner({
  iteration,
  streamingState,
  toolCalls,
  isLoading,
  sessionId,
  taskBoard,
  onCancelExecution,
  onRerunFailed,
  onRetryTask,
  variant = 'overlay',
}: RightPanelProps) {
  // right-panel R1 批次 A: 开合/Tab/最大化/选中产物全部迁入全局 store ——
  // 自动唤起（artifact_created）与消息内联产物卡片需要跨组件写这些状态。
  const open = useRightPanelStore((s) => s.open);
  const tab = useRightPanelStore((s) => s.tab);
  const maximized = useRightPanelStore((s) => s.maximized);
  const selectedArtifactId = useRightPanelStore((s) => s.selectedArtifactId);
  const setTab = useRightPanelStore((s) => s.setTab);
  const setMaximized = useRightPanelStore((s) => s.setMaximized);
  const { artifacts, loading, refresh } = useArtifacts(sessionId);
  const { items: outlineItems, isLoading: outlineLoading } = useConversationOutline(sessionId);
  // R3 批次 C: 变更计数徽标（changesListStore 缓存，ChangesSection 拉取后
  // 这里同步可读；工作区干净/未拉取时不显示计数）
  const changesCount = useChangesListStore((s) => {
    if (!sessionId) return 0;
    const c = s.bySession[sessionId];
    return c && !c.clean ? c.changes.length : 0;
  });
  // P0-3 (UI 优化方案 2026-09-12): 面板宽度可调 —— 拖拽左边缘手柄，
  // 持久化到 localStorage（范围 280~600，默认 320）。
  // 批次 D: applyWidth 供档位按钮/双击重置/键盘调整（clamp + 立即持久化）。
  const {
    width,
    isDragging,
    onMouseDown: onResizeMouseDown,
    applyWidth,
  } = useResizablePanel({
    storageKey: 'right-panel-width',
    minWidth: 280,
    maxWidth: 600,
    defaultWidth: 320,
    anchor: 'right',
  });

  const isPush = variant === 'push';

  // 批次 C: 切会话清掉上一会话的选中产物，避免详情页跨会话串台。
  useEffect(() => {
    useRightPanelStore.getState().clearSelectedArtifact();
  }, [sessionId]);

  // R4 批次 B: 会话切换即预取变更列表 —— 徽标计数即时可用，切到变更 Tab
  // 无首次加载等待；store 层 inflight 去重，重复触发无额外成本。
  useEffect(() => {
    if (!sessionId) return;
    void useChangesListStore.getState().fetch(sessionId);
  }, [sessionId]);

  // 批次 D: Esc 退出最大化（最大化只在 push 模式出现）
  useEffect(() => {
    if (!maximized) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMaximized(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [maximized, setMaximized]);

  // R2 批次 B: overlay 模式 Esc 关闭面板（push 模式 Esc 不关面板，只退最大化）
  useEffect(() => {
    if (isPush || !open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') useRightPanelStore.getState().setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isPush, open]);

  const selected = selectedArtifactId
    ? (artifacts.find((a) => a.id === selectedArtifactId) ?? null)
    : null;

  const activePreset = WIDTH_PRESETS.find((p) => p.width === width)?.label ?? null;
  const showMaximize = isPush;
  const handleClose = () => {
    if (maximized) setMaximized(false);
    useRightPanelStore.getState().setOpen(false);
  };

  const content = (
    <>
      {/* P0-3: 左边缘拖拽手柄 —— 悬停时高亮 + cursor-col-resize 反馈。
          批次 D: 热区加宽到 6px；双击回落默认宽度；方向键 ±32px（a11y）。 */}
      {!maximized && (
        <div
          className="absolute top-0 left-0 h-full w-1.5 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
          onMouseDown={onResizeMouseDown}
          onDoubleClick={() => applyWidth(320)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft') {
              e.preventDefault();
              applyWidth(width + 32);
            } else if (e.key === 'ArrowRight') {
              e.preventDefault();
              applyWidth(width - 32);
            }
          }}
          role="separator"
          aria-orientation="vertical"
          aria-label="拖拽调整面板宽度（左右方向键微调，双击复位）"
          tabIndex={0}
          data-testid="right-panel-resize-handle"
        />
      )}
      {selected ? (
        <PanelHeader
          onClose={handleClose}
          maximized={maximized}
          onToggleMaximize={showMaximize ? () => setMaximized(!maximized) : undefined}
        />
      ) : (
        <PanelHeader
          tab={tab}
          onTabChange={setTab}
          onClose={handleClose}
          maximized={maximized}
          onToggleMaximize={showMaximize ? () => setMaximized(!maximized) : undefined}
          activePreset={activePreset}
          onApplyPreset={applyWidth}
          showAutoOpenToggle={tab === 'artifacts'}
          artifactCount={sessionId ? artifacts.length : 0}
          changesCount={changesCount}
        />
      )}

      <div className="h-[calc(100%-2.5rem)] overflow-y-auto min-h-0">
        {selected && sessionId ? (
          <ArtifactViewer
            artifact={selected}
            sessionId={sessionId}
            onBack={() => useRightPanelStore.getState().clearSelectedArtifact()}
          />
        ) : tab === 'progress' ? (
          <ProgressSection
            iteration={iteration}
            streamingState={streamingState}
            toolCalls={toolCalls}
            isLoading={isLoading}
            taskBoard={taskBoard}
            // S2: todos 从该会话的键控槽位读取（切会话看该会话的清单）
            sessionId={sessionId}
            onCancelExecution={onCancelExecution}
            onRerunFailed={onRerunFailed}
            onRetryTask={onRetryTask}
          />
        ) : tab === 'changes' ? (
          <ChangesSection sessionId={sessionId} />
        ) : tab === 'outline' ? (
          <ConversationOutline items={outlineItems} isLoading={outlineLoading} />
        ) : (
          <ArtifactsSection
            artifacts={artifacts}
            loading={loading}
            sessionId={sessionId}
            onRefresh={refresh}
            onSelect={(a: Artifact) => useRightPanelStore.getState().selectArtifact(a.id)}
            onReveal={(a) => {
              if (sessionId) revealArtifact(sessionId, a.id).catch(() => {});
            }}
          />
        )}
      </div>
    </>
  );

  const isMaximized = maximized && isPush && open;

  // R2 批次 B: overlay 模式半透明遮罩 —— 点击关闭 + 随面板淡入淡出；
  // push 模式无遮罩（面板参与布局，主区仍可见可点）。
  const backdrop =
    !isPush ? (
      <div
        className={
          'fixed inset-0 z-20 bg-black/40 transition-opacity duration-200 ease-in-out ' +
          (open ? 'opacity-100' : 'opacity-0 pointer-events-none')
        }
        onClick={() => useRightPanelStore.getState().setOpen(false)}
        aria-hidden
        data-testid="right-panel-overlay-backdrop"
      />
    ) : null;

  return (
    <>
      {backdrop}
      <aside
        data-testid="right-panel"
        data-open={open ? 'true' : 'false'}
        data-maximized={isMaximized ? 'true' : 'false'}
        aria-hidden={isPush && !open ? true : undefined}
        className={
          isPush
            ? // push: 参与父级 flex 布局，开合动画在宽度上（拖拽时禁用过渡保跟手）
              // 批次 D: 最大化时覆盖内容行（父容器需 relative），宽度样式忽略
              'relative h-full flex-shrink-0 overflow-hidden bg-surface border-l border-border ' +
              (isMaximized ? 'absolute inset-0 z-20 ' : '') +
              (isDragging ? '' : 'transition-[width] duration-200 ease-in-out')
            : // overlay: fixed 覆盖层，平移进出（窄屏/移动端）
              'fixed top-12 right-0 h-[calc(100vh-3rem)] bg-surface border-l border-border ' +
              'transform transition-transform duration-200 ease-in-out z-30 ' +
              (open ? 'translate-x-0' : 'translate-x-full')
        }
        style={isPush ? { width: open ? (isMaximized ? '100%' : `${width}px`) : 0 } : { width: `${width}px` }}
      >
        {isPush ? (
          // push 模式: 内容容器固定宽度，动画期间不被压扁；最大化时随面板铺满
          <div className="h-full" style={{ width: isMaximized ? '100%' : `${width}px` }}>
            {content}
          </div>
        ) : (
          // overlay 模式保持原有直接子元素结构（resize 手柄 parentElement 断言依赖）
          content
        )}
      </aside>
    </>
  );
}

// memo (F1): 面板关闭时仅平移出屏不卸载, memo 避免流式期间无意义的整面板重渲染。
export const RightPanel = memo(RightPanelInner);
