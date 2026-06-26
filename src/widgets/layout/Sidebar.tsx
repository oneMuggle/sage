import { clsx } from 'clsx';
import { MessageSquare, Settings, Brain, BookOpen } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { resolveEndpoint } from '../../entities/setting/types';
import { testEndpointConnection } from '../../features/manage-endpoints/api';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useStoredSiderOrder } from '../../shared/lib/dnd/useStoredSiderOrder';
import { useStore } from '../../shared/lib/store';
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
  { path: '/settings', label: '设置', icon: Settings },
];

interface SidebarProps {
  width?: number;
}

export function Sidebar({ width = 240 }: SidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const {
    sessions,
    currentSessionId,
    setCurrentSessionId,
    createSession,
    loadSessions,
    deleteSession,
  } = useStore();
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

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

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
                window.location.href = '/chat';
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
        return <CronJobSection />;
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
          <div
            className={clsx(
              'w-[7px] h-[7px] rounded-full',
              connectionStatus === 'connected' && 'bg-success',
              connectionStatus === 'not-configured' && 'bg-warning',
              connectionStatus === 'error' && 'bg-error',
            )}
          ></div>
          <span title={latency != null ? `延迟 ${latency}ms` : ''}>
            {connectionStatus === 'connected' &&
              `已连接${latency != null ? ` · ${latency}ms` : ''}`}
            {connectionStatus === 'not-configured' && '未配置'}
            {connectionStatus === 'error' && '连接失败'}
          </span>
          <span className="ml-auto">v0.1.1</span>
        </div>
      </div>
    </aside>
  );
}
