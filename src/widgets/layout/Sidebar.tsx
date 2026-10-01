import { clsx } from 'clsx';
import {
  Bot,
  CalendarClock,
  MessageSquare,
  Settings,
  Brain,
  BookOpen,
  Network,
  Sparkles,
  FileSpreadsheet,
  HelpCircle,
  ListTodo,
  UserCog,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  PenSquare,
  type LucideIcon,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { usePermissionState } from '../../entities/permission/permissionState';
import { useQuestionState } from '../../entities/question/questionState';
import { resolveEndpoint } from '../../entities/setting/types';
import { useArtifactEventsStore } from '../../features/artifacts/artifactEventsStore';
import { useAttentionSnapshot, attentionSummary, attentionTitle } from '../../features/attention';
import { testEndpointConnection } from '../../features/manage-endpoints/api';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useRightPanelStore } from '../../features/right-panel/rightPanelStore';
import { deleteSessionCascade } from '../../features/send-message/useChat';
import { sessionApi } from '../../shared/api/sessionApi';
import { requestOpenCommandPalette } from '../../shared/lib/commandPaletteEvents';
import { unlockFeature, useFeatureUnlock } from '../../shared/lib/hooks/useFeatureUnlock';
import { useI18n } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { AttnBadge, BrandLogo, LiveDot, Tooltip, type LiveState } from '../../shared/ui';
import {
  ConversationsSection,
  GitStatusSection,
  ProjectSection,
  useSiderSections,
} from '../sidebar';

import { SidebarNavItem, type SidebarNavItemData } from './SidebarNavItem';

// UX-IA R1 A3（对标 ChatGPT / Claude Projects）：项目作为一级容器排在会话之上。
// UX-IA R3 批次 0（2026-10-01）：分组从 6 个收敛到 3 个 ——
//   - todos / cron 删除：两者本来就有完整整页（/todos、/scheduled），左栏分组
//     只是「预览前 5 条 + 跳转」，与整页构成同一列里的两个同名入口（"待办"出现两次）。
//     现降级为一级导航项，能力零损失、重复入口消失。
//   - team 删除：占位实现（"占位 - 团队协作将在 Phase 6 接入"），无功能不占位。
// useSiderSections 会用 defaultOrder 过滤存量 localStorage 里的旧 key，
// 老用户残留的 todos/cron/team 会被自动丢弃，无需迁移脚本。
const SECTION_KEYS = ['project', 'conversations', 'git'] as const;
const DEFAULT_COLLAPSED_SECTIONS = ['git'] as const;

// UX-IA R3 批次 B：两段式布局 —— rail 常驻 + 内容列。
//
// 对标 Codex / Cursor / Claude：左栏拆成「56px 功能 rail」与「内容列」两段，
// rail 只放作用域切换（图标），内容列只放列表。带来的三处改善：
//   1. 导航与内容**物理分离**。此前 9 个路由链接与 3~6 个内容分组共享一列，
//      读起来是 15 项平铺列表，没有"导航 / 内容"的层级。
//   2. **单滚动容器**。此前 nav 自身滚动、各 section 内部再各自滚（3 层嵌套）。
//      现在内容列是唯一滚动容器（配合 SiderSection 去掉内层 maxHeight 滚动）。
//   3. 「更多」分组消失。分组折叠是为了压住竖列表的噪音，rail 消除了噪音本身，
//      于是少一级交互、少一个 localStorage 键、少 5 个测试断言。
//
// 宽度契约：`width` 仍是**总宽**（Layout 的 wrapper 与拖拽手柄都按它算，零改动），
// rail 固定 56px 从里面扣，内容列吃剩下的宽度。故 `useResizableSidebar` 的
// 下界/默认值/上界已从 220/240/360 调到 260/300/480 —— 旧的 240 总宽只剩
// 184px 内容列，装不下会话标题。
const RAIL_WIDTH = 56;

interface NavItem {
  path: string;
  label: string;
  labelKey?: 'sidebar.nav.agents';
  icon: LucideIcon;
}

const primaryNavItems: NavItem[] = [
  { path: '/chat', label: '对话', icon: MessageSquare },
  { path: '/todos', label: '待办', icon: ListTodo },
  { path: '/memory', label: '记忆', icon: Brain },
  { path: '/knowledge', label: '知识库', icon: BookOpen },
];
const settingsNavItem: NavItem = { path: '/settings', label: '设置', icon: Settings };
const moreNavItems: NavItem[] = [
  { path: '/scheduled', label: '定时任务', icon: CalendarClock },
  { path: '/office', label: 'Office', icon: FileSpreadsheet },
  { path: '/skills', label: '技能', icon: Sparkles },
  { path: '/agents', label: '智能体', labelKey: 'sidebar.nav.agents', icon: Bot },
  { path: '/orchestration', label: '编排', icon: Network },
  { path: '/arena', label: 'Arena', icon: UserCog },
  { path: '/help', label: '帮助', icon: HelpCircle },
];
// rail 顺序 = 一级在前、次级在后（原先靠「更多」折叠分组表达的顺序感）。
const railNavItems = [...primaryNavItems, ...moreNavItems, settingsNavItem];

/**
 * 渐进式功能披露 (U10)：高级入口路径 → feature key 映射。
 * 这些入口在首次使用前从 sidebar 隐藏，首次使用（访问对应路由）后永久解锁。
 * 隐藏期间仍可经命令面板发现，避免成为无法触达的死功能。
 *
 * 只登记"多数用户不需要"的入口。`/skills` 曾在此处，但技能页是 SKILL.md 体系的
 * 唯一 UI 入口，门控它会形成自锁——入口可见性依赖"已经用过入口"。
 *
 * Arena 自动化（P5 起入口为 `/arena`，旧路径 `/arena-accounts` 重定向并入）
 * 同样面向高级用户，普通用户用不到：
 * 默认隐藏，直接访问 URL 或在设置页开启 Arena 自动化开关后永久解锁。
 */
const ADVANCED_FEATURE_BY_PATH: Record<string, string> = {
  '/orchestration': 'orchestration',
  '/office': 'office',
  '/arena': 'arena-accounts',
  '/arena-accounts': 'arena-accounts',
};

interface SidebarProps {
  width?: number;
  /**
   * 批次 B 之后语义变为「隐藏内容列」：折叠态 = 只剩 56px rail（与批次 0 的
   * 折叠态表现一致），展开态 = rail + 内容列。此前它等价于"整栏折叠"。
   */
  collapsed?: boolean;
  /** 折叠/展开切换回调。提供时在 rail 底部渲染可见 toggle 按钮（不再仅依赖 Ctrl+B）。 */
  onToggleCollapse?: () => void;
}

export function Sidebar({ width = 300, collapsed = false, onToggleCollapse }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useI18n();
  const { sessions, currentSessionId, setCurrentSessionId, loadSessions, updateSession } =
    useStore();
  const { settings } = useSettings();
  const chatEndpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints);
  const [connectionStatus, setConnectionStatus] = useState<
    'connected' | 'not-configured' | 'error'
  >('not-configured');
  const [latency, setLatency] = useState<number | null>(null);

  const {
    order: sectionOrder,
    collapsed: collapsedSections,
    toggleCollapsed,
  } = useSiderSections(SECTION_KEYS, DEFAULT_COLLAPSED_SECTIONS);
  // 会话排序完全交给后端 SQL (`SessionRepository.list()`):
  //   is_pinned DESC, run_status IN ('running','suspended') DESC, updated_at DESC
  // 前端不再持有 localStorage 拖拽顺序。

  // U9: Live-Dot vs Attention-Badge 分离。
  // 待处理数 = 审批与提问两个串行卡点之和（后端单 agent 循环，各至多 1 项挂起），
  // 以 AttnBadge（带数字）挂在「对话」导航入口上 —— 语义是"需要你做什么"。
  const pendingApprovals = usePermissionState((s) => (s.currentRequest != null ? 1 : 0));
  const pendingQuestions = useQuestionState((s) => (s.currentQuestion != null ? 1 : 0));
  const attentionCount = pendingApprovals + pendingQuestions;

  // UX-IA R3 批次 D（UI 接线）：rail 底部的**统一**待处理总数。
  // 此前只有「对话」入口的角标（审批+提问），其余来源（未读产物、待办、未提交
  // 改动）散落在各自面板里各自计数，用户没有一处能看到"总共多少件事等我处理"。
  // 取数全部走 features/attention 单一来源，展示层不再自行 if。
  const artifactCount = useArtifactEventsStore((s) =>
    currentSessionId ? (s.counts[currentSessionId] ?? 0) : 0,
  );
  const seenArtifactCount = useRightPanelStore(
    (s) => (currentSessionId ? (s.seenArtifactCount[currentSessionId] ?? 0) : 0),
  );
  const attention = useAttentionSnapshot({
    sessionId: currentSessionId,
    unseenArtifacts: Math.max(0, artifactCount - seenArtifactCount),
  });

  // 存活状态：rail 底部 LiveDot（无数字）只表达"系统是否活着" ——
  // connected=working（accent 脉冲）、not-configured=sleeping（暗色静态点）；
  // 连接失败属于"需要注意"语义，改由 AttnBadge 承载。
  const liveState: LiveState =
    connectionStatus === 'connected'
      ? 'working'
      : connectionStatus === 'not-configured'
        ? 'sleeping'
        : 'idle';

  // 渐进式功能披露 (U10)：高级入口的解锁状态。
  const [orchestrationUnlocked] = useFeatureUnlock('orchestration');
  const [officeUnlocked] = useFeatureUnlock('office');
  const [arenaAccountsUnlocked] = useFeatureUnlock('arena-accounts');
  const unlockedByFeature: Record<string, boolean> = {
    orchestration: orchestrationUnlocked,
    office: officeUnlocked,
    'arena-accounts': arenaAccountsUnlocked,
  };

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // 首次访问高级功能路由即永久解锁其 sidebar 入口（sticky unlock）。
  useEffect(() => {
    const featureKey = ADVANCED_FEATURE_BY_PATH[location.pathname];
    if (featureKey) {
      unlockFeature(featureKey);
    }
  }, [location.pathname]);

  useEffect(() => {
    if (!chatEndpoint?.baseUrl || !chatEndpoint.apiKey) {
      setConnectionStatus('not-configured');
      return;
    }
    testEndpointConnection(
      chatEndpoint.baseUrl,
      chatEndpoint.apiKey,
      settings.modelSelections.chatModel.modelId ?? undefined,
    )
      .then((result) => {
        setConnectionStatus(result.success ? 'connected' : 'error');
        setLatency(result.latency ?? null);
      })
      .catch(() => {
        setConnectionStatus('error');
      });
  }, [chatEndpoint?.baseUrl, chatEndpoint?.apiKey, settings.modelSelections.chatModel.modelId]);

  const handleNewSession = () => {
    // Phase 7: 新建会话跳转到欢迎屏，由用户在欢迎屏输入后再创建 session
    navigate('/welcome');
  };

  const handleOpenSearch = () => {
    // 与 Ctrl/Cmd+K 同一入口：命令面板内含全局搜索（会话/记忆/知识库）
    requestOpenCommandPalette();
  };

  // 会话切换统一入口（会话列表 onSelect 与项目模块 onOpenSession 共用）
  const handleOpenSession = (id: string) => {
    setCurrentSessionId(id);
    if (location.pathname !== '/chat') {
      // SPA navigation: avoid `window.location.href` which would
      // trigger a full page reload and produce a visible flash.
      navigate('/chat');
    }
  };

  // U4': 重命名——API 成功后原地更新 store(侧栏/聊天头部即时同步),不整表 reload
  const handleRenameSession = async (sessionId: string, title: string) => {
    try {
      const updated = await sessionApi.rename(sessionId, title);
      updateSession(sessionId, { title: updated.title });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(t('session.rename_failed').replace('{message}', message));
    }
  };

  /** 渐进披露门控：未解锁的高级入口不渲染。 */
  const isRevealed = (item: NavItem): boolean => {
    const featureKey = ADVANCED_FEATURE_BY_PATH[item.path];
    return !featureKey || unlockedByFeature[featureKey];
  };

  /** NavItem → SidebarNavItemData（解析 i18n labelKey）。 */
  const toNavData = (item: NavItem): SidebarNavItemData => ({
    path: item.path,
    label: item.labelKey === 'sidebar.nav.agents' ? t('sidebar.nav.agents') : item.label,
    icon: item.icon,
  });

  const isActivePath = (path: string): boolean =>
    location.pathname === path || (path === '/chat' && location.pathname === '/');

  const renderSection = (key: string) => {
    const isCollapsed = collapsedSections.has(key);

    switch (key) {
      case 'conversations':
        return (
          <ConversationsSection
            sessions={sessions}
            currentSessionId={currentSessionId}
            collapsed={isCollapsed}
            onToggleCollapsed={() => toggleCollapsed(key)}
            onSelect={handleOpenSession}
            onDelete={(id) => void deleteSessionCascade(id)}
            onNewSession={handleNewSession}
            onRename={handleRenameSession}
            onRefreshSessions={loadSessions}
          />
        );
      case 'git':
        return (
          <GitStatusSection
            collapsed={isCollapsed}
            onToggleCollapsed={() => toggleCollapsed(key)}
          />
        );
      case 'project':
        return (
          <ProjectSection
            collapsed={isCollapsed}
            onToggleCollapsed={() => toggleCollapsed(key)}
            onOpenSession={handleOpenSession}
          />
        );
      default:
        return null;
    }
  };

  return (
    <aside
      style={{ width: `${width}px` }}
      className="h-screen bg-ui-panel border-r border-border flex flex-shrink-0"
    >
      {/* ═══ 第一段：56px 功能 rail（常驻） ═══ */}
      <div
        data-testid="sidebar-rail"
        style={{ width: `${RAIL_WIDTH}px` }}
        className="h-full flex flex-col items-center flex-shrink-0 border-r border-border"
      >
        {/* 品牌 logo 标记（wordmark 在内容列头部，避免同屏两个同 alt 的 logo img） */}
        <div className="h-12 flex items-center justify-center border-b border-border w-full">
          <BrandLogo size="sm" />
        </div>

        {/* 作用域切换：图标 + Tooltip + sr-only 文本标签 */}
        <nav
          data-testid="sidebar-rail-nav"
          className="flex-1 py-2 flex flex-col items-center gap-1 overflow-y-auto w-full"
        >
          {railNavItems
            .filter((item) => item.path !== settingsNavItem.path)
            .map((item) => {
              if (!isRevealed(item)) {
                return null;
              }

              return (
                <SidebarNavItem
                  key={item.path}
                  item={toNavData(item)}
                  active={isActivePath(item.path)}
                  variant="rail"
                  trailing={
                    item.path === '/chat' ? <AttnBadge count={attentionCount} /> : undefined
                  }
                />
              );
            })}
        </nav>

        {/* 底部：设置 → 存活点 → 折叠/展开 */}
        <div className="pb-2 w-full flex flex-col items-center gap-1.5">
          <Tooltip content={settingsNavItem.label} side="right">
            <Link
              to={settingsNavItem.path}
              aria-label={settingsNavItem.label}
              data-testid="sidebar-settings-link"
              className={clsx(
                'flex items-center justify-center w-10 h-10 rounded-radius-sm transition-colors',
                location.pathname === settingsNavItem.path
                  ? 'bg-primary/10 text-primary'
                  : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary',
              )}
            >
              <Settings className="w-5 h-5" />
              <span className="sr-only">{settingsNavItem.label}</span>
            </Link>
          </Tooltip>

          {/* U9: LiveDot 只表达存活；连接失败由下方 AttnBadge 作为"待处理"呈现 */}
          <div className="flex items-center gap-1 justify-center">
            <LiveDot
              state={liveState}
              workingTitle={latency != null ? `已连接 · 延迟 ${latency}ms` : '已连接'}
              sleepingTitle="未配置端点"
            />
            {connectionStatus === 'error' && (
              <AttnBadge count={1} title="连接失败,请检查端点配置" />
            )}
          </div>

          {/* 批次 D（UI 接线）：统一待处理总数。折叠态 rail 也常驻，
              因此"侧栏已收起"不再等于"提醒看不见"。明细见 title。 */}
          <Tooltip
            content={
              attention.total > 0
                ? `${attentionTitle(attention)} · ${attentionSummary(attention)}`
                : attentionTitle(attention)
            }
            side="right"
          >
            <div
              data-testid="sidebar-attention-total"
              className="flex justify-center w-full"
              aria-live="polite"
            >
              <AttnBadge count={attention.total} />
            </div>
          </Tooltip>

          {onToggleCollapse && (
            <button
              type="button"
              onClick={onToggleCollapse}
              aria-label={collapsed ? '展开侧边栏' : '折叠侧边栏'}
              title={collapsed ? '展开侧边栏 (Ctrl+B)' : '折叠侧边栏 (Ctrl+B)'}
              data-testid={collapsed ? 'sidebar-expand-button' : 'sidebar-collapse-button'}
              className="flex items-center justify-center w-10 h-10 rounded-radius-sm text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
            >
              {collapsed ? <PanelLeftOpen className="w-5 h-5" /> : <PanelLeftClose className="w-5 h-5" />}
            </button>
          )}
        </div>
      </div>

      {/* ═══ 第二段：内容列（折叠时整段不渲染） ═══ */}
      {!collapsed && (
        <div data-testid="sidebar-content" className="flex-1 min-w-0 flex flex-col">
          <div className="h-12 flex items-center px-4 border-b border-border flex-shrink-0">
            <span className="font-semibold text-sm text-text">{t('sidebar.brand')}</span>
          </div>

          {/* UX-IA R1 A1：顶部主操作条（对标 ChatGPT「新聊天 / 搜索聊天」） */}
          <div
            className="px-2 pt-2 flex items-center gap-1"
            data-testid="sidebar-primary-actions"
          >
            <button
              type="button"
              onClick={handleNewSession}
              aria-label="新建对话"
              data-testid="sidebar-new-chat-primary"
              title="新建对话 (Ctrl+N)"
              className="flex-1 flex items-center gap-2.5 px-3 py-2 rounded-radius-sm border border-border text-sm font-medium text-text-primary hover:bg-bg-hover transition-colors"
            >
              <PenSquare className="w-4 h-4" />
              <span>新建对话</span>
            </button>
            <Tooltip content="搜索 (Ctrl+K)" side="bottom">
              <button
                type="button"
                onClick={handleOpenSearch}
                aria-label="搜索"
                data-testid="sidebar-search-button"
                className="flex items-center justify-center w-9 h-9 rounded-radius-sm border border-border text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
              >
                <Search className="w-4 h-4" />
              </button>
            </Tooltip>
          </div>

          {/* 唯一滚动容器：此前 nav 自身滚动 + 各 section 内部再滚（3 层嵌套） */}
          <nav className="flex-1 min-h-0 py-2 px-2 overflow-y-auto" data-testid="sidebar-scroll">
            {sectionOrder.map((key) => (
              <div key={key}>{renderSection(key)}</div>
            ))}
          </nav>

          {/* 底部状态栏：连接状态文字 + 版本号 */}
          <div className="px-2 pt-2 border-t border-border flex-shrink-0">
            <div className="flex items-center gap-2 px-2 py-1.5 text-[11px] text-muted">
              <span title={latency != null ? `延迟 ${latency}ms` : ''}>
                {connectionStatus === 'connected' &&
                  `已连接${latency != null ? ` · ${latency}ms` : ''}`}
                {connectionStatus === 'not-configured' && '未配置'}
                {connectionStatus === 'error' && '连接失败'}
              </span>
              <span className="ml-auto">v{__APP_VERSION__}</span>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
