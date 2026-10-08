// src/widgets/chat/RightPanel.tsx
import { Bell, BellOff, Maximize2, Minimize2, SlidersHorizontal, X } from 'lucide-react';
import { memo, useCallback, useEffect, useRef, useState } from 'react';

import type { Artifact } from '../../features/artifacts/artifactApi';
import { revealArtifact } from '../../features/artifacts/artifactApi';
import { useArtifacts } from '../../features/artifacts/useArtifacts';
import { useChangesListStore } from '../../features/changes/changesListStore';
import { requestMessageJump } from '../../features/chat/messageJumpStore';
import {
  useConversationOutline,
  type OutlineItem,
} from '../../features/chat/useConversationOutline';
import { useConversationTurns, type TurnItem } from '../../features/chat/useConversationTurns';
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
import { TrajectoryPane } from './TrajectoryPane';
import { TurnList } from './TurnList';
import { ArtifactViewer } from './artifacts/ArtifactViewer';
import { ArtifactsSection } from './artifacts/ArtifactsSection';
import { ChangesSection } from './changes/ChangesSection';
import { DocumentPreview } from './preview/DocumentPreview';
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
  // RD23 (round52): 历史编排选取回调。
  onSelectRun?: (run: import('../../shared/api/orchRunClient').OrchRunDetail) => void;
  // P1 (UI 优化方案 2026-09-13): push = 参与 flex 挤压主区（Claude
  // artifacts 风格，桌面端）；overlay = fixed 覆盖层（窄屏/移动端回退）。
  variant?: 'overlay' | 'push';
}

const RIGHT_PANEL_TABS: readonly RightPanelTab[] = [
  'progress',
  'outline',
  'trajectory',
  'changes',
  'preview',
  'artifacts',
];

const TAB_LABELS: Record<RightPanelTab, string> = {
  progress: '进度',
  artifacts: '产物',
  changes: '变更',
  outline: '目录',
  trajectory: '轨迹',
  preview: '预览',
};

/**
 * 宽度档位（right-panel R1 批次 D，对齐 Claude 的小/中/大三档）。
 *
 * 2026-09-29 面板密度调整：320/440/560 在 5 个 Tab + 操作区并排时每个 Tab
 * 只剩 ~30px，「产物 (12)」放不下。档位整体上移到 360/520/720，
 * L 档才有足够宽度铺开变更/预览这类宽内容。
 */
const WIDTH_PRESETS = [
  { label: 'S', width: 360 },
  { label: 'M', width: 520 },
  { label: 'L', width: 720 },
] as const;

/** 面板默认宽度（= S 档；拖拽手柄双击复位也回落至此） */
const DEFAULT_PANEL_WIDTH = 360;

/** 拖拽宽度上下限（下限留给三档操作区，上限放开以容纳宽内容） */
const MIN_PANEL_WIDTH = 280;
const MAX_PANEL_WIDTH = 900;

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

/**
 * 产物自动唤起开关（就地读写 localStorage；事件侧 isArtifactAutoOpenEnabled 同源）。
 *
 * 2026-09-29 由顶栏铃铛图标按钮改为「选项」浮层内的一行 —— 铃铛独占
 * 32px 顶栏空间，而它只服务于产物 Tab，常态展示属于空间浪费。
 */
function AutoOpenToggleRow() {
  const [enabled, setEnabled] = useState(() => isArtifactAutoOpenEnabled());
  return (
    <button
      aria-pressed={enabled}
      className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-xs text-text-secondary transition-colors hover:bg-bg-hover hover:text-text"
      onClick={() => {
        const next = !enabled;
        setArtifactAutoOpenEnabled(next);
        setEnabled(next);
      }}
      title={enabled ? '产物创建时自动展开面板：开' : '产物创建时自动展开面板：关'}
      data-testid="right-panel-auto-open-toggle"
    >
      {enabled ? <Bell className="w-3.5 h-3.5" /> : <BellOff className="w-3.5 h-3.5" />}
      <span className="flex-1 text-left">产物自动展开</span>
    </button>
  );
}

interface PanelOptionsMenuProps {
  activePreset?: string | null;
  onApplyPreset?: (width: number) => void;
  showAutoOpenToggle?: boolean;
}

/**
 * 顶栏「选项」浮层：收纳宽度档位 + 产物自动展开开关。
 *
 * 2026-09-29 之前这两组控件平铺在 Tab 行右侧，占掉 ~92px（3 个档位按钮
 * 60px + 铃铛 32px），5 个 Tab 挤到每个 ~30px。收进浮层后 Tab 行只保留
 * 最大化/关闭两个图标，每个 Tab 多拿 ~18px。
 */
function PanelOptionsMenu({
  activePreset,
  onApplyPreset,
  showAutoOpenToggle,
}: PanelOptionsMenuProps) {
  const hasItems = Boolean(onApplyPreset) || Boolean(showAutoOpenToggle);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 点击浮层外 / Esc 收起。hasItems 为假时不注册监听。
  useEffect(() => {
    if (!open || !hasItems) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, hasItems]);

  if (!hasItems) return null;

  return (
    <div className="relative" ref={ref}>
      <button
        className="p-2 text-text-secondary hover:text-text hover:bg-bg-hover rounded transition-colors"
        onClick={() => setOpen((v) => !v)}
        title="面板选项（宽度档位 / 产物自动展开）"
        aria-label="面板选项"
        aria-haspopup="true"
        aria-expanded={open}
        data-testid="right-panel-options-toggle"
      >
        <SlidersHorizontal className="w-4 h-4" />
      </button>
      {open && (
        // 披露式浮层（disclosure popover），非 role=menu：本浮层内是普通
        // 切换按钮，未实现方向键导航，挂 menu 角色属于半套 ARIA 实现。
        <div
          aria-label="面板选项"
          className="absolute right-0 top-full z-30 mt-1 w-44 rounded-md border border-border bg-surface py-1 shadow-lg"
        >
          {onApplyPreset && (
            <>
              <div className="px-3 pt-1 pb-0.5 text-[10px] text-text-muted">面板宽度</div>
              {WIDTH_PRESETS.map((p) => (
                <button
                  key={p.label}
                  aria-pressed={activePreset === p.label}
                  className={
                    'flex w-full items-center gap-2 rounded px-3 py-1.5 text-xs transition-colors ' +
                    'hover:bg-bg-hover ' +
                    (activePreset === p.label ? 'text-primary' : 'text-text-secondary')
                  }
                  onClick={() => {
                    onApplyPreset(p.width);
                    setOpen(false);
                  }}
                  title={`面板宽度：${p.label}（${p.width}px）`}
                  aria-label={`面板宽度档位 ${p.label}`}
                  data-testid={`right-panel-preset-${p.label}`}
                >
                  <span className="w-3 text-center font-medium">{p.label}</span>
                  <span className="flex-1 text-left">{p.width}px</span>
                </button>
              ))}
            </>
          )}
          {showAutoOpenToggle && (
            <>
              {onApplyPreset && <div className="my-1 border-t border-border" aria-hidden />}
              <AutoOpenToggleRow />
            </>
          )}
        </div>
      )}
    </div>
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

  // list 视图:Progress / Artifacts tabs + 选项/最大化/× 按钮
  if (tab !== undefined && onTabChange) {
    const countOf = (t: RightPanelTab) =>
      t === 'artifacts' ? artifactCount : t === 'changes' ? changesCount : 0;
    return (
      <div className="flex border-b border-border items-center pr-1">
        {RIGHT_PANEL_TABS.map((t) => {
          const count = countOf(t);
          return (
            <button
              key={t}
              // 计数压成小号数字而非「(N)」后缀：Tab 行在 S 档下每个 Tab
              // 只有 ~50px，带括号的形式会截断。aria-label 保留「产物 (N)」
              // 完整读法，屏幕阅读器与既有测试断言不受影响。
              aria-label={count > 0 ? `${TAB_LABELS[t]} (${count})` : TAB_LABELS[t]}
              className={
                'flex-1 min-w-0 truncate py-2 text-sm font-medium transition-colors ' +
                (tab === t
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-text-secondary hover:text-text')
              }
              onClick={() => onTabChange(t)}
            >
              {TAB_LABELS[t]}
              {count > 0 && (
                <span className="ml-0.5 text-[10px] tabular-nums opacity-70">{count}</span>
              )}
            </button>
          );
        })}
        <div className="flex items-center gap-0.5 ml-1 shrink-0">
          <PanelOptionsMenu
            activePreset={activePreset}
            onApplyPreset={onApplyPreset}
            showAutoOpenToggle={showAutoOpenToggle}
          />
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
  onSelectRun,
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
  // 对标 U1（ZCode ConversationTurnNavigator）：轮次导航数据源
  const { items: turnItems } = useConversationTurns(sessionId);
  // R3 批次 C: 变更计数徽标（changesListStore 缓存，ChangesSection 拉取后
  // 这里同步可读；工作区干净/未拉取时不显示计数）
  const changesCount = useChangesListStore((s) => {
    if (!sessionId) return 0;
    const c = s.bySession[sessionId];
    return c && !c.clean ? c.changes.length : 0;
  });
  // P0-3 (UI 优化方案 2026-09-12): 面板宽度可调 —— 拖拽左边缘手柄，
  // 持久化到 localStorage。
  // 批次 D: applyWidth 供选项浮层档位/双击重置/键盘调整（clamp + 立即持久化）。
  // 2026-09-29: 范围放宽到 280~900、默认 360（5 个 Tab 不再挤在 320px 里）。
  const {
    width,
    isDragging,
    onMouseDown: onResizeMouseDown,
    applyWidth,
  } = useResizablePanel({
    storageKey: 'right-panel-width',
    minWidth: MIN_PANEL_WIDTH,
    maxWidth: MAX_PANEL_WIDTH,
    defaultWidth: DEFAULT_PANEL_WIDTH,
    anchor: 'right',
  });

  const isPush = variant === 'push';

  // 对话阅读导航 A2: 大纲条目 → 定位到对应标题。最大化 / overlay 模式下
  // 面板遮住了对话区，先让出视图再定位。
  const handleOutlineSelect = useCallback(
    (item: OutlineItem, headingIndex: number) => {
      if (maximized) setMaximized(false);
      if (!isPush) useRightPanelStore.getState().setOpen(false);
      requestMessageJump({ messageId: item.messageId, headingText: item.text, headingIndex });
    },
    [isPush, maximized, setMaximized],
  );

  // 对标 U1: 轮次条目 → 定位到该轮 user 消息。收起面板逻辑与大纲一致。
  const handleTurnSelect = useCallback(
    (item: TurnItem) => {
      if (maximized) setMaximized(false);
      if (!isPush) useRightPanelStore.getState().setOpen(false);
      requestMessageJump({ messageId: item.messageId });
    },
    [isPush, maximized, setMaximized],
  );

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

  // 2026-09-29: 产物详情页也保留 Tab 行 —— 此前详情态只给「最大化/×」，
  // 离开必须先点「返回」，想看进度得回列表再切，形成死胡同。
  // 切 Tab 一律先清掉选中产物：否则点了「进度」仍停在详情页。
  const handleTabChange = useCallback(
    (next: RightPanelTab) => {
      useRightPanelStore.getState().clearSelectedArtifact();
      setTab(next);
    },
    [setTab],
  );
  // 详情态高亮「产物」，让 Tab 行的选中态与实际内容一致。
  const activeTab: RightPanelTab = selected ? 'artifacts' : tab;

  const content = (
    <>
      {/* P0-3: 左边缘拖拽手柄 —— 悬停时高亮 + cursor-col-resize 反馈。
          批次 D: 热区加宽到 6px；双击回落默认宽度；方向键 ±32px（a11y）。 */}
      {!maximized && (
        <div
          className="absolute top-0 left-0 h-full w-1.5 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
          onMouseDown={onResizeMouseDown}
          onDoubleClick={() => applyWidth(DEFAULT_PANEL_WIDTH)}
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
      <PanelHeader
        tab={activeTab}
        onTabChange={handleTabChange}
        onClose={handleClose}
        maximized={maximized}
        onToggleMaximize={showMaximize ? () => setMaximized(!maximized) : undefined}
        activePreset={activePreset}
        onApplyPreset={applyWidth}
        showAutoOpenToggle={activeTab === 'artifacts'}
        artifactCount={sessionId ? artifacts.length : 0}
        changesCount={changesCount}
      />

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
            onSelectRun={onSelectRun}
          />
        ) : tab === 'changes' ? (
          <ChangesSection sessionId={sessionId} />
        ) : tab === 'outline' ? (
          <>
            {/* 对标 U1: 轮次导航——目录上方，按用户输入切分对话 */}
            <div className="pt-2">
              <div
                className="px-3 pb-1 text-[11px] font-medium text-muted"
                data-testid="turn-list-heading"
              >
                轮次
              </div>
              <TurnList items={turnItems} onSelect={handleTurnSelect} />
            </div>
            <div className="border-t border-border" />
            <ConversationOutline
              items={outlineItems}
              isLoading={outlineLoading}
              onSelect={handleOutlineSelect}
            />
          </>
        ) : tab === 'trajectory' ? (
          /* 对标 F3: 模型轨迹——会话级时间线 + 搜索 + 工具 payload */
          <TrajectoryPane sessionId={sessionId} />
        ) : tab === 'preview' ? (
          useRightPanelStore.getState().previewFilePath ? (
            <DocumentPreview filePath={useRightPanelStore.getState().previewFilePath!} />
          ) : (
            <div className="flex items-center justify-center py-8 text-sm text-text-muted">
              从变更卡片点击「预览」打开文档
            </div>
          )
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
  const backdrop = !isPush ? (
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
        style={
          isPush
            ? { width: open ? (isMaximized ? '100%' : `${width}px`) : 0 }
            : { width: `${width}px` }
        }
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
