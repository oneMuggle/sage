import { Command } from 'cmdk';
import { Folder } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { useTheme } from '../../app/providers/useTheme';
import { backendRequest } from '../../shared/api/backendRequest';
import { projectApi, type ProjectSummary } from '../../shared/api/projectApi';
import { getRecentWikiProjects } from '../../shared/api-client/wiki';
import { useStore } from '../../shared/lib/store';

import { actionCommands, navCommands } from './commandItems';

// ⌘1-9 快捷键跳转 (U6 from OpenWorker)
const KEYBOARD_SHORTCUTS = ['1', '2', '3', '4', '5', '6', '7', '8', '9'];

/** P9: 知识搜索范围 localStorage 键（'' 或未设置 = 默认最近打开） */
const KNOWLEDGE_SCOPE_KEY = 'sage:knowledge-scope:v1';

/** P1-3.7: 全局搜索返回类型（后端 /api/v1/search/global）。 */
interface GlobalSearchResult {
  sessions?: Array<{ id: string; title: string; updated_at: number; message_count: number }>;
  memories?: Array<{
    id: string;
    content: string;
    memory_type: string;
    importance: number;
    tags: string[];
  }>;
  knowledge?: Array<{ path: string; title: string; snippet: string }>;
  /** P7: 项目模块接入全局搜索 */
  projects?: Array<{ id: string; name: string; path: string; session_count: number }>;
}

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate();
  const { sessions, setCurrentSessionId, createSession, loadSessions } = useStore();
  const { resolved, setMode } = useTheme();
  const [search, setSearch] = useState('');
  const [globalResults, setGlobalResults] = useState<GlobalSearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  // P9: 知识搜索范围（wiki 项目根目录；'' = 默认最近打开），localStorage 持久化
  const [knowledgeScope, setKnowledgeScope] = useState<string>(
    () => localStorage.getItem(KNOWLEDGE_SCOPE_KEY) ?? '',
  );
  const [wikiRecents, setWikiRecents] = useState<Array<{ path: string; name: string }>>([]);
  const abortRef = useRef<AbortController | null>(null);

  // 打开时重置搜索
  useEffect(() => {
    if (open) {
      setSearch('');
      setGlobalResults(null);
      // 项目模块 P2: 打开面板即刷新项目清单（失败静默降级为不显示分组）
      projectApi
        .list()
        .then(setProjects)
        .catch(() => setProjects([]));
      // P9: 拉取最近 wiki 项目供"知识范围"分组（失败静默降级为不显示）
      getRecentWikiProjects()
        .then((recents) => setWikiRecents(recents.map((r) => ({ path: r.path, name: r.name }))))
        .catch(() => setWikiRecents([]));
    }
  }, [open]);

  // P1-3.7: 当搜索词 >= 2 字符时，debounce 300ms 调用后端全局搜索
  useEffect(() => {
    if (search.length < 2) {
      setGlobalResults(null);
      return;
    }

    // Cancel in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const params = new URLSearchParams({ q: search, limit: '10' });
        // P9: 显式知识范围（未设置时后端回退最近打开的项目）
        if (knowledgeScope) {
          params.set('knowledge_project', knowledgeScope);
        }
        const result = await backendRequest<GlobalSearchResult>({
          path: `/api/v1/search/global?${params}`,
        });
        if (!controller.signal.aborted) {
          setGlobalResults(result);
        }
      } catch {
        // Backend unavailable — silently degrade to command-only mode
        if (!controller.signal.aborted) {
          setGlobalResults(null);
        }
      } finally {
        if (!controller.signal.aborted) {
          setSearching(false);
        }
      }
    }, 300);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [search, knowledgeScope]);

  const handleNav = useCallback(
    (path: string) => {
      navigate(path);
      onOpenChange(false);
    },
    [navigate, onOpenChange],
  );

  const handleNewChat = useCallback(async () => {
    const sessionId = await createSession();
    setCurrentSessionId(sessionId);
    navigate('/chat');
    onOpenChange(false);
  }, [createSession, setCurrentSessionId, navigate, onOpenChange]);

  const handleToggleTheme = useCallback(() => {
    setMode(resolved === 'light' ? 'dark' : 'light');
    onOpenChange(false);
  }, [setMode, resolved, onOpenChange]);

  const handleOpenSession = useCallback(
    (sessionId: string) => {
      setCurrentSessionId(sessionId);
      navigate('/chat');
      onOpenChange(false);
    },
    [setCurrentSessionId, navigate, onOpenChange],
  );

  // 项目模块 P2/P7: 打开项目（复用最近会话或新建并绑定）后进入会话。
  // 只消费 id —— 命令模式清单与搜索命中两种来源共用。
  const handleOpenProject = useCallback(
    async (project: { id: string }) => {
      try {
        const { session } = await projectApi.open(project.id);
        await loadSessions();
        handleOpenSession(session.id);
      } catch (err) {
        onOpenChange(false);
        toast.error(`打开项目失败：${err instanceof Error ? err.message : String(err)}`);
      }
    },
    [handleOpenSession, loadSessions, onOpenChange],
  );

  // P9: 设置知识搜索范围（持久化 localStorage；选择是调参，不关闭面板）
  const handleSetKnowledgeScope = useCallback((path: string) => {
    setKnowledgeScope(path);
    try {
      localStorage.setItem(KNOWLEDGE_SCOPE_KEY, path);
    } catch {
      // localStorage 不可用时仅本次会话生效
    }
  }, []);

  // 项目模块 P2: 登记项目（原生选目录 → register → open → 进入新会话）
  const handleAddProject = useCallback(async () => {
    const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
    if (!api) {
      toast.error('添加项目失败：IPC 桥接不可用');
      return;
    }
    try {
      const picked = await api.selectDirectory({ intent: 'open' });
      if (!picked) return; // 用户取消
      const project = await projectApi.register(picked);
      const { session } = await projectApi.open(project.id);
      await loadSessions();
      handleOpenSession(session.id);
    } catch (err) {
      toast.error(`添加项目失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }, [handleOpenSession, loadSessions]);

  /**
   * 项目模块 P2: 操作命令分派收敛 —— 键盘 ⌘数字 与 onSelect 两条路径
   * 原先各自维护一份 if/else，新增 action 必须双点同步；统一走这里。
   */
  const runAction = useCallback(
    (id: string) => {
      if (id === 'new-chat') void handleNewChat();
      else if (id === 'toggle-theme') handleToggleTheme();
      else if (id === 'add-project') void handleAddProject();
    },
    [handleAddProject, handleNewChat, handleToggleTheme],
  );

  // 最近会话（按时间排序，取前 8 个）
  const recentSessions = [...sessions]
    .sort((a, b) => (b.last_message_at ?? b.updated_at) - (a.last_message_at ?? a.updated_at))
    .slice(0, 8);

  // ⌘1-9 快捷键跳转 (U6 from OpenWorker)
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && KEYBOARD_SHORTCUTS.includes(e.key)) {
        e.preventDefault();
        const index = parseInt(e.key) - 1;

        // 导航命令优先
        if (index < navCommands.length) {
          handleNav(navCommands[index].path);
          return;
        }

        // 然后是操作命令
        const actionIndex = index - navCommands.length;
        if (actionIndex < actionCommands.length) {
          runAction(actionCommands[actionIndex].id);
          return;
        }

        // 最后是最近会话
        const sessionIndex = index - navCommands.length - actionCommands.length;
        if (sessionIndex < recentSessions.length) {
          handleOpenSession(recentSessions[sessionIndex].id);
        }
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, recentSessions, handleNav, runAction, handleOpenSession]);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="命令面板"
      className="fixed top-[20%] left-1/2 -translate-x-1/2 w-full max-w-lg bg-surface border border-border rounded-radius-lg shadow-xl overflow-hidden z-50 animate-cmdk-enter"
      shouldFilter={search.length < 2}
    >
      <div className="flex items-center border-b border-border px-3">
        <Command.Input
          value={search}
          onValueChange={setSearch}
          placeholder="输入命令或搜索..."
          className="w-full h-12 bg-transparent text-sm text-text placeholder:text-text-muted outline-none"
          autoFocus
        />
      </div>
      <Command.List className="max-h-80 overflow-y-auto p-1.5">
        {search.length < 2 && (
          <Command.Empty className="py-6 text-center text-sm text-text-muted">
            无匹配结果
          </Command.Empty>
        )}

        {/* 命令模式（搜索词 < 2 字符）：导航 + 操作 + 最近会话 */}
        {search.length < 2 && (
          <>
            {/* 导航 */}
            <Command.Group heading="导航" className="mb-1.5">
              {navCommands.map((item, index) => {
                const Icon = item.icon;
                const shortcut = KEYBOARD_SHORTCUTS[index];
                return (
                  <Command.Item
                    key={item.path}
                    value={item.label}
                    onSelect={() => handleNav(item.path)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <Icon className="w-4 h-4 text-text-muted" />
                    <span className="flex-1">{item.label}</span>
                    {shortcut && (
                      <kbd className="ml-auto text-xs text-faint bg-bg-muted px-1.5 py-0.5 rounded border border-line">
                        ⌘{shortcut}
                      </kbd>
                    )}
                  </Command.Item>
                );
              })}
            </Command.Group>

            {/* 操作 */}
            <Command.Group heading="操作" className="mb-1.5">
              {actionCommands.map((cmd, index) => {
                const Icon = cmd.icon;
                const shortcut = KEYBOARD_SHORTCUTS[navCommands.length + index];
                return (
                  <Command.Item
                    key={cmd.id}
                    value={`${cmd.label} ${cmd.description}`}
                    onSelect={() => runAction(cmd.id)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <Icon className="w-4 h-4 text-text-muted" />
                    <div className="flex-1">
                      <div className="font-medium">{cmd.label}</div>
                      <div className="text-xs text-text-muted">{cmd.description}</div>
                    </div>
                    {shortcut && (
                      <kbd className="ml-auto text-xs text-faint bg-bg-muted px-1.5 py-0.5 rounded border border-line">
                        ⌘{shortcut}
                      </kbd>
                    )}
                  </Command.Item>
                );
              })}
            </Command.Group>

            {/* 项目模块 P2: 最近项目（打开 = 复用最近会话或新建并绑定） */}
            {projects.length > 0 && (
              <Command.Group heading="项目" className="mb-1.5">
                {projects.slice(0, 8).map((project) => (
                  <Command.Item
                    key={project.id}
                    value={`project-${project.name}-${project.path}`}
                    onSelect={() => void handleOpenProject(project)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <Folder className="w-4 h-4 text-text-muted shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="truncate">{project.name}</div>
                      <div className="text-xs text-text-muted truncate">{project.path}</div>
                    </div>
                    {project.sessionCount > 0 && (
                      <span className="ml-auto text-xs text-text-muted">
                        {project.sessionCount} 个会话
                      </span>
                    )}
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* P9: 知识范围（作用于搜索模式的知识结果；选择不关闭面板） */}
            {wikiRecents.length > 0 && (
              <Command.Group heading="知识范围" className="mb-1.5">
                <Command.Item
                  value="knowledge-scope-default"
                  onSelect={() => handleSetKnowledgeScope('')}
                  className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                >
                  <span className="w-4 shrink-0 text-center text-xs text-primary">
                    {knowledgeScope === '' && '✓'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="truncate">默认（最近打开）</div>
                    <div className="text-xs text-text-muted truncate">
                      知识搜索跟随最近打开的 wiki 项目
                    </div>
                  </div>
                </Command.Item>
                {/* P13: 全部最近 wiki 项目（逗号分隔多根，跨项目合并搜索） */}
                {wikiRecents.length > 1 && (
                  <Command.Item
                    value="knowledge-scope-all"
                    onSelect={() =>
                      handleSetKnowledgeScope(wikiRecents.map((r) => r.path).join(','))
                    }
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <span className="w-4 shrink-0 text-center text-xs text-primary">
                      {knowledgeScope === wikiRecents.map((r) => r.path).join(',') && '✓'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="truncate">全部最近 wiki 项目</div>
                      <div className="text-xs text-text-muted truncate">
                        跨项目合并搜索（{wikiRecents.length} 个）
                      </div>
                    </div>
                  </Command.Item>
                )}
                {wikiRecents.slice(0, 5).map((recent) => (
                  <Command.Item
                    key={recent.path}
                    value={`knowledge-scope-${recent.path}`}
                    onSelect={() => handleSetKnowledgeScope(recent.path)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <span className="w-4 shrink-0 text-center text-xs text-primary">
                      {knowledgeScope === recent.path && '✓'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="truncate">{recent.name || recent.path}</div>
                      <div className="text-xs text-text-muted truncate">{recent.path}</div>
                    </div>
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {/* 最近会话 */}
            {recentSessions.length > 0 && (
              <Command.Group heading="最近会话">
                {recentSessions.map((session) => (
                  <Command.Item
                    key={session.id}
                    value={session.title}
                    onSelect={() => handleOpenSession(session.id)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <span className="truncate">{session.title || '新对话'}</span>
                    <span className="ml-auto text-xs text-text-muted">
                      {session.message_count} 条消息
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </>
        )}

        {/* P1-3.7: 全局搜索结果（搜索词 >= 2 字符时显示） */}
        {search.length >= 2 && searching && (
          <Command.Item
            disabled
            value="searching"
            className="py-4 text-center text-sm text-text-muted"
          >
            搜索中…
          </Command.Item>
        )}
        {search.length >= 2 && !searching && globalResults && (
          <>
            {globalResults.sessions && globalResults.sessions.length > 0 && (
              <Command.Group heading="会话">
                {globalResults.sessions.map((s) => (
                  <Command.Item
                    key={s.id}
                    value={`session-${s.id}-${s.title}`}
                    onSelect={() => handleOpenSession(s.id)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <span className="truncate">{s.title || '新对话'}</span>
                    <span className="ml-auto text-xs text-text-muted">
                      {s.message_count} 条消息
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {globalResults.memories && globalResults.memories.length > 0 && (
              <Command.Group heading="记忆">
                {globalResults.memories.map((m) => (
                  <Command.Item
                    key={m.id}
                    value={`memory-${m.id}-${m.content.slice(0, 50)}`}
                    onSelect={() => {
                      navigate('/memory');
                      onOpenChange(false);
                    }}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <span className="flex-1 truncate">{m.content.slice(0, 80)}</span>
                    <span className="text-xs text-text-muted">{m.memory_type}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {globalResults.knowledge && globalResults.knowledge.length > 0 && (
              <Command.Group heading="知识库">
                {globalResults.knowledge.map((k) => (
                  <Command.Item
                    key={k.path}
                    value={`knowledge-${k.path}-${k.title}`}
                    onSelect={() => {
                      navigate('/knowledge');
                      onOpenChange(false);
                    }}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="truncate">{k.title || k.path}</div>
                      <div className="text-xs text-text-muted truncate">{k.snippet}</div>
                    </div>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {/* P7: 项目搜索命中（名称/路径片段 → 打开项目） */}
            {globalResults.projects && globalResults.projects.length > 0 && (
              <Command.Group heading="项目" className="mb-1.5">
                {globalResults.projects.map((p) => (
                  <Command.Item
                    key={p.id}
                    value={`search-project-${p.name}-${p.path}`}
                    onSelect={() => void handleOpenProject(p)}
                    className="flex items-center gap-2.5 px-3 py-2 rounded-radius-sm text-sm text-text cursor-default select-none aria-selected:bg-primary/10 aria-selected:text-primary data-[disabled]:opacity-50 transition-colors"
                  >
                    <Folder className="w-4 h-4 text-text-muted shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="truncate">{p.name}</div>
                      <div className="text-xs text-text-muted truncate">{p.path}</div>
                    </div>
                    {p.session_count > 0 && (
                      <span className="ml-auto text-xs text-text-muted">
                        {p.session_count} 个会话
                      </span>
                    )}
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {!globalResults.sessions?.length &&
              !globalResults.memories?.length &&
              !globalResults.knowledge?.length &&
              !globalResults.projects?.length && (
                <div className="py-6 text-center text-sm text-text-muted">无匹配结果</div>
              )}
          </>
        )}
      </Command.List>

      {/* 底部提示 */}
      <div className="flex items-center justify-between border-t border-border px-3 py-2 text-xs text-text-muted">
        <span>↑↓ 导航</span>
        <span>⌘1-9 跳转</span>
        <span>↵ 选择</span>
        <span>esc 关闭</span>
      </div>
    </Command.Dialog>
  );
}
