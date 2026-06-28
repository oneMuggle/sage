import { clsx } from 'clsx';
import { MessageSquare, Settings, Brain, BookOpen, Clock } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { resolveEndpoint } from '../../entities/setting/types';
import { testEndpointConnection } from '../../features/manage-endpoints/api';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useStore } from '../../shared/lib/store';
import { SessionItem } from '../session/SessionItem';

// 导航项配置
const navItems = [
  { path: '/chat', label: '对话', icon: MessageSquare },
  { path: '/memory', label: '记忆', icon: Brain },
  { path: '/knowledge', label: '知识库', icon: BookOpen },
  { path: '/scheduled', label: '定时任务', icon: Clock },
  { path: '/settings', label: '设置', icon: Settings },
];

export function Sidebar() {
  const location = useLocation();
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

  const handleNewSession = async () => {
    const sessionId = await createSession();
    setCurrentSessionId(sessionId);
  };

  return (
    <aside className="w-60 h-screen bg-surface border-r border-border flex flex-col flex-shrink-0">
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

        {/* 最近对话 */}
        <div className="text-[11px] font-semibold uppercase tracking-wide text-muted px-3 pt-4 pb-2">
          最近对话
        </div>
        <button
          onClick={handleNewSession}
          className="w-full text-left px-3 py-1.5 rounded-radius-sm transition-colors text-xs text-text-secondary hover:bg-bg-hover flex items-center gap-2"
        >
          + 新对话
        </button>
        <div className="overflow-y-auto max-h-[calc(100vh-320px)]">
          {sessions.map((session) => (
            <SessionItem
              key={session.id}
              session={session}
              isActive={session.id === currentSessionId}
              onSelect={() => {
                setCurrentSessionId(session.id);
                if (location.pathname !== '/chat') {
                  window.location.href = '/chat';
                }
              }}
              onDelete={() => deleteSession(session.id)}
            />
          ))}
        </div>
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
