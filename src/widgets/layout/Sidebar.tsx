import { clsx } from 'clsx';
import {
  MessageSquare,
  Settings,
  Brain,
  BookOpen,
  Network,
  Sparkles,
  FileSpreadsheet,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { usePermissionState } from '../../entities/permission/permissionState';
import { useQuestionState } from '../../entities/question/questionState';
import { resolveEndpoint } from '../../entities/setting/types';
import { testEndpointConnection } from '../../features/manage-endpoints/api';
import { useSettings } from '../../features/manage-settings/useSettings';
import { sessionApi } from '../../shared/api/sessionApi';
import { useStoredSiderOrder } from '../../shared/lib/dnd/useStoredSiderOrder';
import { unlockFeature, useFeatureUnlock } from '../../shared/lib/hooks/useFeatureUnlock';
import { useI18n } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { AttnBadge, BrandLogo, LiveDot, type LiveState } from '../../shared/ui';
import {
  ConversationsSection,
  CronJobSection,
  ProjectSection,
  TeamSection,
  useSiderSections,
} from '../sidebar';

const SECTION_KEYS = ['conversations', 'cron', 'project', 'team'] as const;
const SESSION_ORDER_KEY = 'sage:sider:order:v1';

// 导航项配置
const navItems = [
  { path: '/chat', label: '对话', icon: MessageSquare },
  { path: '/memory', label: '记忆', icon: Brain },
  { path: '/knowledge', label: '知识库', icon: BookOpen },
  { path: '/orchestration', label: '编排', icon: Network },
  { path: '/skills', label: '技能', icon: Sparkles },
  { path: '/office', label: 'Office', icon: FileSpreadsheet },
  { path: '/settings', label: '设置', icon: Settings },
];

/**
 * 渐进式功能披露 (U10)：高级入口路径 → feature key 映射。
 * 这些入口在首次使用前从 sidebar 隐藏，首次使用（访问对应路由）后永久解锁。
 * 隐藏期间仍可经命令面板发现，避免成为无法触达的死功能。
 *
 * 只登记"多数用户不需要"的入口。`/skills` 曾在此处，但技能页是 SKILL.md 体系的
 * 唯一 UI 入口，门控它会形成自锁——入口可见性依赖"已经用过入口"。
 */
const ADVANCED_FEATURE_BY_PATH: Record<string, string> = {
  '/orchestration': 'orchestration',
  '/office': 'office',
};

interface SidebarProps {
  width?: number;
  /** P1-3.6 (UI 优化方案 2026-09-13): 折叠态 → 56px icon rail。
   *  仅渲染品牌 logo + 导航图标，隐藏会话列表/sections/文字标签。 */
  collapsed?: boolean;
}

export function Sidebar({ width = 240, collapsed = false }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useI18n();
  const {
    sessions,
    currentSessionId,
    setCurrentSessionId,
    loadSessions,
    deleteSession,
    updateSession,
  } = useStore();
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
  } = useSiderSections(SECTION_KEYS);
  const { orderedItems, reorder } = useStoredSiderOrder({
    storageKey: SESSION_ORDER_KEY,
    items: sessions,
    getId: (s) => s.id,
  });
  const orderedSessionIds = orderedItems.map((s) => s.id);

  // U9: Live-Dot vs Attention-Badge 分离。
  // 待处理数 = 审批与提问两个串行卡点之和（后端单 agent 循环，各至多 1 项挂起），
  // 以 AttnBadge（带数字）挂在「对话」导航入口上 —— 语义是"需要你做什么"。
  const pendingApprovals = usePermissionState((s) => (s.currentRequest != null ? 1 : 0));
  const pendingQuestions = useQuestionState((s) => (s.currentQuestion != null ? 1 : 0));
  const attentionCount = pendingApprovals + pendingQuestions;

  // 存活状态：页脚 LiveDot（无数字）只表达"系统是否活着" ——
  // connected=working（accent 脉冲）、not-configured=sleeping（暗色静态点）；
  // 连接失败属于"需要注意"语义，改由 AttnBadge 承载（见页脚）。
  const liveState: LiveState =
    connectionStatus === 'connected'
      ? 'working'
      : connectionStatus === 'not-configured'
        ? 'sleeping'
        : 'idle';

  // 渐进式功能披露 (U10)：高级入口的解锁状态。
  const [orchestrationUnlocked] = useFeatureUnlock('orchestration');
  const [officeUnlocked] = useFeatureUnlock('office');
  const unlockedByFeature: Record<string, boolean> = {
    orchestration: orchestrationUnlocked,
    office: officeUnlocked,
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

  const renderSection = (key: string) => {
    const isCollapsed = collapsedSections.has(key);

    switch (key) {
      case 'conversations':
        return (
          <ConversationsSection
            sessions={orderedItems}
            order={orderedSessionIds}
            currentSessionId={currentSessionId}
            collapsed={isCollapsed}
            onToggleCollapsed={() => toggleCollapsed(key)}
            onSelect={(id) => {
              setCurrentSessionId(id);
              if (location.pathname !== '/chat') {
                // SPA navigation: avoid `window.location.href` which would
                // trigger a full page reload and produce a visible flash.
                navigate('/chat');
              }
            }}
            onDelete={(id) => deleteSession(id)}
            onNewSession={handleNewSession}
            onRename={handleRenameSession}
            onOrderChange={(newOrder) => {
              const oldIndex = orderedSessionIds.indexOf(String(newOrder[0]));
              const newIndex = newOrder.indexOf(String(newOrder[0]));
              if (oldIndex !== -1 && newIndex !== -1) {
                reorder(oldIndex, newIndex);
              }
            }}
          />
        );
      case 'cron':
        return (
          <CronJobSection collapsed={isCollapsed} onToggleCollapsed={() => toggleCollapsed(key)} />
        );
      case 'project':
        return (
          <ProjectSection collapsed={isCollapsed} onToggleCollapsed={() => toggleCollapsed(key)} />
        );
      case 'team':
        return (
          <TeamSection collapsed={isCollapsed} onToggleCollapsed={() => toggleCollapsed(key)} />
        );
      default:
        return null;
    }
  };

  // P1-3.6 (UI 优化方案 2026-09-13): 折叠态 icon rail —— 仅渲染品牌 logo + 导航图标，
  // 隐藏文字标签/会话列表/sections。宽度由 Layout 固定 56px。
  if (collapsed) {
    return (
      <aside
        data-testid="sidebar-rail"
        style={{ width: `${width}px` }}
        className="h-screen bg-surface border-r border-border flex flex-col items-center flex-shrink-0"
      >
        {/* 品牌 logo（无 wordmark） */}
        <div className="h-12 flex items-center justify-center border-b border-border w-full">
          <BrandLogo size="sm" />
        </div>

        {/* 导航图标（无文字标签） */}
        <nav className="flex-1 py-2 flex flex-col items-center gap-1 overflow-y-auto w-full">
          {navItems.map((item) => {
            const featureKey = ADVANCED_FEATURE_BY_PATH[item.path];
            if (featureKey && !unlockedByFeature[featureKey]) {
              return null;
            }

            const isActive =
              location.pathname === item.path ||
              (item.path === '/chat' && location.pathname === '/');
            const Icon = item.icon;

            return (
              <Link
                key={item.path}
                to={item.path}
                title={item.label}
                className={clsx(
                  'flex items-center justify-center w-10 h-10 rounded-radius-sm transition-colors',
                  isActive ? 'bg-primary/10 text-primary' : 'text-text-secondary hover:bg-bg-hover',
                )}
              >
                <Icon className="w-5 h-5" />
              </Link>
            );
          })}
        </nav>

        {/* 底部状态：仅连接点 */}
        <div className="pb-2 w-full flex justify-center">
          <LiveDot
            state={liveState}
            workingTitle={latency != null ? `已连接 · 延迟 ${latency}ms` : '已连接'}
            sleepingTitle="未配置端点"
          />
        </div>
      </aside>
    );
  }

  return (
    <aside
      style={{ width: `${width}px` }}
      className="h-screen bg-surface border-r border-border flex flex-col flex-shrink-0"
    >
      {/* U-Brand: 替换 197-202 的硬编码 S+Sage 块为共享 <BrandLogo withWordmark />，wordmark 用 sidebar.brand */}
      <div className="h-12 flex items-center px-4 border-b border-border">
        <BrandLogo size="sm" withWordmark />
      </div>

      {/* 导航列表 */}
      <nav className="flex-1 py-2 px-2 overflow-y-auto">
        {navItems.map((item) => {
          // 渐进式功能披露 (U10)：高级入口未解锁前不渲染。
          const featureKey = ADVANCED_FEATURE_BY_PATH[item.path];
          if (featureKey && !unlockedByFeature[featureKey]) {
            return null;
          }

          const isActive =
            location.pathname === item.path || (item.path === '/chat' && location.pathname === '/');
          const Icon = item.icon;

          return (
            <Link
              key={item.path}
              to={item.path}
              className={clsx(
                'flex items-center gap-2.5 px-3 py-2 rounded-radius-sm transition-colors text-sm font-medium',
                isActive ? 'bg-primary/10 text-primary' : 'text-text-secondary hover:bg-bg-hover',
              )}
            >
              <Icon className="w-4 h-4" />
              <span>{item.label}</span>
              {/* U9: 对话入口的待处理数量（AttnBadge，带数字） */}
              {item.path === '/chat' && <AttnBadge count={attentionCount} />}
            </Link>
          );
        })}

        {/* 可折叠分组 */}
        {sectionOrder.map((key) => (
          <div key={key}>{renderSection(key)}</div>
        ))}
      </nav>

      {/* 底部状态栏 */}
      <div className="px-2 pt-2 border-t border-border">
        <div className="flex items-center gap-2 px-2 py-1.5 text-[11px] text-muted">
          {/* U9: LiveDot 只表达存活（connected=working / not-configured=sleeping，
              error 时熄灭）；连接失败由下方 AttnBadge 作为"待处理"呈现 */}
          <LiveDot
            state={liveState}
            workingTitle={latency != null ? `已连接 · 延迟 ${latency}ms` : '已连接'}
            sleepingTitle="未配置端点"
          />
          <span title={latency != null ? `延迟 ${latency}ms` : ''}>
            {connectionStatus === 'connected' &&
              `已连接${latency != null ? ` · ${latency}ms` : ''}`}
            {connectionStatus === 'not-configured' && '未配置'}
            {connectionStatus === 'error' && '连接失败'}
          </span>
          {connectionStatus === 'error' && <AttnBadge count={1} title="连接失败,请检查端点配置" />}
          <span className="ml-auto">v{__APP_VERSION__}</span>
        </div>
      </div>
    </aside>
  );
}
