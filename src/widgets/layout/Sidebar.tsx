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

import { usePermissionState } from '../../entities/permission/permissionState';
import { useQuestionState } from '../../entities/question/questionState';
import { resolveEndpoint } from '../../entities/setting/types';
import { testEndpointConnection } from '../../features/manage-endpoints/api';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useStoredSiderOrder } from '../../shared/lib/dnd/useStoredSiderOrder';
import { unlockFeature, useFeatureUnlock } from '../../shared/lib/hooks/useFeatureUnlock';
import { useStore } from '../../shared/lib/store';
import { AttnBadge, LiveDot, type LiveState } from '../../shared/ui';
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
 */
const ADVANCED_FEATURE_BY_PATH: Record<string, string> = {
  '/orchestration': 'orchestration',
  '/skills': 'skills',
  '/office': 'office',
};

interface SidebarProps {
  width?: number;
}

export function Sidebar({ width = 240 }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { sessions, currentSessionId, setCurrentSessionId, loadSessions, deleteSession } =
    useStore();
  const { settings } = useSettings();
  const chatEndpoint = resolveEndpoint(settings.modelSelections.chatModel, settings.endpoints);
  const [connectionStatus, setConnectionStatus] = useState<
    'connected' | 'not-configured' | 'error'
  >('not-configured');
  const [latency, setLatency] = useState<number | null>(null);

  const { order: sectionOrder, collapsed, toggleCollapsed } = useSiderSections(SECTION_KEYS);
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
  const [skillsUnlocked] = useFeatureUnlock('skills');
  const [officeUnlocked] = useFeatureUnlock('office');
  const unlockedByFeature: Record<string, boolean> = {
    orchestration: orchestrationUnlocked,
    skills: skillsUnlocked,
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

  const renderSection = (key: string) => {
    const isCollapsed = collapsed.has(key);

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

  return (
    <aside
      style={{ width: `${width}px` }}
      className="h-screen bg-surface border-r border-border flex flex-col flex-shrink-0"
    >
      {/* Logo 区域 */}
      <div className="h-12 flex items-center px-4 border-b border-border">
        <div className="w-6 h-6 bg-primary rounded-sm flex items-center justify-center text-text-inverse font-bold text-xs mr-2.5">
          S
        </div>
        <span className="font-semibold text-sm text-text">Sage</span>
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
          <span className="ml-auto">v0.1.1</span>
        </div>
      </div>
    </aside>
  );
}
