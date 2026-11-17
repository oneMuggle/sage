# Sage - 前端设计

## 9.1 前端概览

### 9.1.1 技术栈

| 层级 | 技术         | 版本  | 说明         |
| ---- | ------------ | ----- | ------------ |
| 框架 | React        | 18.x  | 成熟稳定     |
| 构建 | Vite         | 5.x   | 快速开发     |
| 状态 | Zustand      | 4.x   | 轻量状态管理 |
| 样式 | Tailwind CSS | 3.x   | Chatbox 同款 |
| 路由 | React Router | 6.x   | SPA 路由     |
| 组件 | Headless UI  | 2.x   | 无样式组件库 |
| i18n | i18next      | 23.x  | 多语言       |
| 图标 | Lucide       | 0.3xx | 轻量图标     |

### 9.1.2 目录结构

```
src/
├── components/
│   ├── chat/              # 聊天组件
│   │   ├── ChatInput.tsx
│   │   ├── MessageList.tsx
│   │   ├── Message.tsx
│   │   ├── TypingIndicator.tsx
│   │   └── MessageActions.tsx
│   ├── session/           # 会话组件
│   │   ├── SessionList.tsx
│   │   ├── SessionItem.tsx
│   │   └── NewSessionButton.tsx
│   ├── memory/            # 记忆组件
│   │   ├── MemoryBrowser.tsx
│   │   ├── MemoryItem.tsx
│   │   └── MemorySearch.tsx
│   ├── settings/          # 设置组件
│   │   ├── SettingsPanel.tsx
│   │   ├── ModelSettings.tsx
│   │   └── ThemeSettings.tsx
│   └── common/            # 通用组件
│       ├── Button.tsx
│       ├── Input.tsx
│       ├── Modal.tsx
│       └── Tooltip.tsx
├── pages/
│   ├── Chat.tsx           # 主聊天页
│   ├── Memory.tsx         # 记忆浏览页
│   ├── Settings.tsx       # 设置页
│   └── Skills.tsx         # 技能商店页
├── hooks/
│   ├── useChat.ts         # 聊天逻辑
│   ├── useSessions.ts     # 会话管理
│   ├── useMemory.ts       # 记忆操作
│   └── useAgent.ts        # Agent 交互
├── lib/
│   ├── api.ts             # Tauri API 调用
│   ├── store.ts           # Zustand store
│   └── utils.ts           # 工具函数
├── i18n/                  # 国际化
│   ├── index.ts
│   └── locales/
│       ├── zh-CN.json
│       └── en.json
├── App.tsx
├── main.tsx
└── index.css              # Tailwind 入口
```

---

## 9.2 UI 设计

### 9.2.1 布局结构

```
┌─────────────────────────────────────────────────────────────────┐
│  ┌─────┐                                               Sage  │
│  │ ≡  │                                                       │
├────────────┬────────────────────────────────────────────────────┤
│            │                                                     │
│  会话列表   │                                                     │
│            │                                                     │
│  ┌──────┐ │  ┌──────────────────────────────────────────────┐ │
│  │新对话│ │  │                                              │ │
│  └──────┘ │  │                                              │ │
│            │  │              消息列表区域                     │ │
│  ┌──────┐ │  │                                              │ │
│  │对话 1│ │  │                                              │ │
│  ├──────┤ │  │                                              │ │
│  │对话 2│ │  │                                              │ │
│  ├──────┤ │  └──────────────────────────────────────────────┘ │
│  │对话 3│ │                                                     │
│  └──────┘ │  ┌──────────────────────────────────────────────┐ │
│            │  │ [记忆] [技能] [设置]         [发送 ▶]        │ │
│            │  └──────────────────────────────────────────────┘ │
└────────────┴────────────────────────────────────────────────────┘
```

### 9.2.2 主题色

```css
/* CSS Variables for Theming */
:root {
  /* Light Theme */
  --color-primary: #4f46e5; /* 靛蓝色主色 */
  --color-primary-hover: #4338ca;
  --color-secondary: #10b981; /* 翠绿色 */
  --color-accent: #f59e0b; /* 琥珀色 */

  --color-bg: #ffffff;
  --color-bg-secondary: #f9fafb;
  --color-bg-tertiary: #f3f4f6;

  --color-text: #111827;
  --color-text-secondary: #6b7280;
  --color-text-muted: #9ca3af;

  --color-border: #e5e7eb;
  --color-border-hover: #d1d5db;

  --color-success: #10b981;
  --color-error: #ef4444;
  --color-warning: #f59e0b;
}

[data-theme='dark'] {
  --color-primary: #818cf8;
  --color-primary-hover: #a5b4fc;

  --color-bg: #111827;
  --color-bg-secondary: #1f2937;
  --color-bg-tertiary: #374151;

  --color-text: #f9fafb;
  --color-text-secondary: #d1d5db;
  --color-text-muted: #9ca3af;

  --color-border: #374151;
  --color-border-hover: #4b5563;
}
```

### 9.2.3 字体

```css
/* font-family */
font-family:
  - 'Inter', system-ui, -apple-system, sans-serif;  /* UI */
  - 'JetBrains Mono', monospace;  /* 代码 */
  - 'Noto Sans SC', 'PingFang SC', sans-serif;  /* 中文 */
```

---

## 9.3 组件设计

### 9.3.1 ChatInput

```tsx
// components/chat/ChatInput.tsx
import { useState, useRef } from 'react';
import { Send, Square, Loader2 } from 'lucide-react';
import { Button } from '../common/Button';

interface ChatInputProps {
  onSend: (message: string) => void;
  onInterrupt?: () => void;
  isLoading?: boolean;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({
  onSend,
  onInterrupt,
  isLoading = false,
  disabled = false,
  placeholder = '输入消息...',
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    if (!value.trim() || isLoading) return;
    onSend(value.trim());
    setValue('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Auto-resize textarea
  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  };

  return (
    <div className="flex items-end gap-2 border-t p-4 bg-white dark:bg-gray-800">
      {/* 功能按钮 */}
      <div className="flex gap-1">
        <Button
          variant="ghost"
          size="sm"
          title="记忆"
          // onClick={() => openMemoryModal()}
        >
          💭
        </Button>
        <Button
          variant="ghost"
          size="sm"
          title="技能"
          // onClick={() => openSkillsModal()}
        >
          ⚡
        </Button>
        <Button
          variant="ghost"
          size="sm"
          title="设置"
          // onClick={() => navigate('/settings')}
        >
          ⚙️
        </Button>
      </div>

      {/* 输入框 */}
      <div className="flex-1 relative">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className={`
            w-full resize-none rounded-lg border px-4 py-3
            bg-gray-50 dark:bg-gray-700
            border-gray-200 dark:border-gray-600
            focus:outline-none focus:ring-2 focus:ring-primary/50
            disabled:opacity-50
            max-h-[200px]
          `}
        />
      </div>

      {/* 发送按钮 */}
      {isLoading ? (
        <Button variant="danger" onClick={onInterrupt} title="停止">
          <Square className="w-5 h-5" />
        </Button>
      ) : (
        <Button variant="primary" onClick={handleSend} disabled={!value.trim() || disabled}>
          <Send className="w-5 h-5" />
        </Button>
      )}
    </div>
  );
}
```

### 9.3.2 Message

```tsx
// components/chat/Message.tsx
import { useState } from 'react';
import { Copy, ThumbsUp, ThumbsDown, MoreHorizontal } from 'lucide-react';
import type { Message as MessageType } from '../../lib/api';

interface MessageProps {
  message: MessageType;
  onFeedback?: (messageId: string, feedback: 'up' | 'down') => void;
}

export function Message({ message, onFeedback }: MessageProps) {
  const [showActions, setShowActions] = useState(false);

  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';

  return (
    <div
      className={`
        flex ${isUser ? 'justify-end' : 'justify-start'}
        mb-4
      `}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      <div
        className={`
          max-w-[80%] rounded-2xl px-4 py-3
          ${
            isUser
              ? 'bg-primary text-white rounded-br-md'
              : 'bg-gray-100 dark:bg-gray-700 rounded-bl-md'
          }
        `}
      >
        {/* 消息内容 */}
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>

        {/* 工具调用显示 */}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-2 text-xs opacity-75">
            🔧 使用工具: {message.tool_calls.map((tc) => tc.name).join(', ')}
          </div>
        )}

        {/* 底部信息 */}
        <div
          className={`
          flex items-center gap-2 mt-1 text-xs
          ${isUser ? 'text-white/70' : 'text-gray-500 dark:text-gray-400'}
        `}
        >
          <span>{new Date(message.created_at).toLocaleTimeString()}</span>
          {message.tokens && <span>{message.tokens} tokens</span>}
        </div>

        {/* 操作按钮 */}
        {showActions && isAssistant && (
          <div
            className={`
            flex items-center gap-1 mt-2 pt-2 border-t
            ${isUser ? 'border-white/20' : 'border-gray-200 dark:border-gray-600'}
          `}
          >
            <button
              onClick={() => navigator.clipboard.writeText(message.content)}
              className="p-1 rounded hover:bg-black/10 dark:hover:bg-white/10"
              title="复制"
            >
              <Copy className="w-4 h-4" />
            </button>

            {onFeedback && (
              <>
                <button
                  onClick={() => onFeedback(message.id, 'up')}
                  className="p-1 rounded hover:bg-black/10"
                  title="有帮助"
                >
                  <ThumbsUp className="w-4 h-4" />
                </button>
                <button
                  onClick={() => onFeedback(message.id, 'down')}
                  className="p-1 rounded hover:bg-black/10"
                  title="没帮助"
                >
                  <ThumbsDown className="w-4 h-4" />
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

### 9.3.3 SessionList

```tsx
// components/session/SessionList.tsx
import { useState } from 'react';
import { Plus, Search, MoreVertical, Trash2, Pin } from 'lucide-react';
import { SessionItem } from './SessionItem';
import { Button } from '../common/Button';

interface Session {
  id: string;
  title: string;
  updated_at: number;
  is_pinned?: boolean;
}

interface SessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onPin: (id: string) => void;
}

export function SessionList({
  sessions,
  currentSessionId,
  onSelect,
  onNew,
  onDelete,
  onPin,
}: SessionListProps) {
  const [searchQuery, setSearchQuery] = useState('');

  const filteredSessions = sessions.filter((s) =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const pinned = filteredSessions.filter((s) => s.is_pinned);
  const unpinned = filteredSessions.filter((s) => !s.is_pinned);

  return (
    <div className="flex flex-col h-full">
      {/* 搜索 */}
      <div className="p-3 border-b">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="搜索会话..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="
              w-full pl-9 pr-3 py-2 rounded-lg
              bg-gray-100 dark:bg-gray-700
              border-none focus:outline-none focus:ring-2 focus:ring-primary/50
              text-sm
            "
          />
        </div>
      </div>

      {/* 新建按钮 */}
      <div className="p-3">
        <Button variant="primary" className="w-full" onClick={onNew}>
          <Plus className="w-4 h-4 mr-2" />
          新对话
        </Button>
      </div>

      {/* 会话列表 */}
      <div className="flex-1 overflow-y-auto">
        {/* 置顶会话 */}
        {pinned.length > 0 && (
          <div className="px-3 py-1">
            <div className="text-xs text-gray-500 dark:text-gray-400 px-2 mb-1">置顶</div>
            {pinned.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isActive={session.id === currentSessionId}
                onSelect={() => onSelect(session.id)}
                onDelete={() => onDelete(session.id)}
                onPin={() => onPin(session.id)}
              />
            ))}
          </div>
        )}

        {/* 普通会话 */}
        {unpinned.length > 0 && (
          <div className="px-3 py-1">
            {pinned.length > 0 && (
              <div className="text-xs text-gray-500 dark:text-gray-400 px-2 mb-1">最近</div>
            )}
            {unpinned.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isActive={session.id === currentSessionId}
                onSelect={() => onSelect(session.id)}
                onDelete={() => onDelete(session.id)}
                onPin={() => onPin(session.id)}
              />
            ))}
          </div>
        )}

        {/* 空状态 */}
        {filteredSessions.length === 0 && (
          <div className="text-center text-gray-500 dark:text-gray-400 py-8 text-sm">
            {searchQuery ? '未找到匹配的会话' : '暂无会话'}
          </div>
        )}
      </div>
    </div>
  );
}
```

### 9.3.4 MemoryBrowser

```tsx
// components/memory/MemoryBrowser.tsx
import { useState, useEffect } from 'react';
import { Search, Filter, Trash2, Edit2, Tag } from 'lucide-react';
import { Button } from '../common/Button';
import { Input } from '../common/Input';

interface Memory {
  id: string;
  content: string;
  summary?: string;
  memory_type: 'episodic' | 'semantic';
  importance: number;
  created_at: number;
  tags: string[];
}

interface MemoryBrowserProps {
  memories: Memory[];
  onSearch: (query: string) => void;
  onDelete: (id: string) => void;
  onEdit: (id: string, content: string) => void;
}

export function MemoryBrowser({ memories, onSearch, onDelete, onEdit }: MemoryBrowserProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<'all' | 'episodic' | 'semantic'>('all');
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchQuery) {
        onSearch(searchQuery);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, onSearch]);

  const filteredMemories = memories.filter((m) => {
    if (filterType !== 'all' && m.memory_type !== filterType) return false;
    return true;
  });

  const getImportanceColor = (importance: number) => {
    if (importance >= 8) return 'text-red-500';
    if (importance >= 6) return 'text-orange-500';
    if (importance >= 4) return 'text-yellow-500';
    return 'text-gray-400';
  };

  return (
    <div className="flex flex-col h-full">
      {/* 搜索和过滤 */}
      <div className="p-4 border-b space-y-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="搜索记忆..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="
              w-full pl-9 pr-3 py-2 rounded-lg
              bg-gray-100 dark:bg-gray-700
              border-none focus:outline-none focus:ring-2 focus:ring-primary/50
            "
          />
        </div>

        <div className="flex gap-2">
          {(['all', 'episodic', 'semantic'] as const).map((type) => (
            <button
              key={type}
              onClick={() => setFilterType(type)}
              className={`
                px-3 py-1 rounded-full text-sm
                ${
                  filterType === type
                    ? 'bg-primary text-white'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
                }
              `}
            >
              {type === 'all' ? '全部' : type === 'episodic' ? '情景' : '语义'}
            </button>
          ))}
        </div>
      </div>

      {/* 记忆列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {filteredMemories.map((memory) => (
          <div
            key={memory.id}
            className="
              p-4 rounded-lg border
              bg-white dark:bg-gray-800
              border-gray-200 dark:border-gray-700
              hover:border-primary/50 transition-colors
            "
          >
            {/* 头部 */}
            <div className="flex items-start justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className={getImportanceColor(memory.importance)}>
                  {'★'.repeat(Math.ceil(memory.importance / 2))}
                </span>
                <span className="text-xs text-gray-500">
                  {memory.memory_type === 'episodic' ? '情景记忆' : '语义记忆'}
                </span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setEditingId(editingId === memory.id ? null : memory.id)}
                  className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                >
                  <Edit2 className="w-4 h-4 text-gray-400" />
                </button>
                <button
                  onClick={() => onDelete(memory.id)}
                  className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                >
                  <Trash2 className="w-4 h-4 text-red-400" />
                </button>
              </div>
            </div>

            {/* 内容 */}
            {editingId === memory.id ? (
              <div className="space-y-2">
                <textarea
                  defaultValue={memory.content}
                  className="
                    w-full p-2 rounded border
                    bg-gray-50 dark:bg-gray-700
                    focus:outline-none focus:ring-2 focus:ring-primary/50
                  "
                  rows={4}
                />
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                    取消
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => {
                      // TODO: 保存编辑
                      setEditingId(null);
                    }}
                  >
                    保存
                  </Button>
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-700 dark:text-gray-300">{memory.content}</p>
            )}

            {/* 标签 */}
            {memory.tags && memory.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {memory.tags.map((tag) => (
                  <span
                    key={tag}
                    className="
                      px-2 py-0.5 rounded-full text-xs
                      bg-gray-100 dark:bg-gray-700
                      text-gray-600 dark:text-gray-400
                    "
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}

            {/* 时间 */}
            <div className="text-xs text-gray-400 mt-2">
              {new Date(memory.created_at).toLocaleString()}
            </div>
          </div>
        ))}

        {filteredMemories.length === 0 && (
          <div className="text-center text-gray-500 dark:text-gray-400 py-8">暂无记忆</div>
        )}
      </div>
    </div>
  );
}
```

---

## 9.4 状态管理

### 9.4.1 Zustand Store

```typescript
// lib/store.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface Session {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  is_pinned?: boolean;
}

interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  tool_calls?: ToolCall[];
  created_at: number;
  tokens?: number;
}

interface AppState {
  // 会话
  sessions: Session[];
  currentSessionId: string | null;

  // 消息
  messages: Record<string, Message[]>;

  // UI 状态
  isTyping: boolean;
  sidebarOpen: boolean;

  // 记忆
  memories: Memory[];
  memorySearchQuery: string;

  // Actions
  setSessions: (sessions: Session[]) => void;
  setCurrentSession: (id: string | null) => void;
  addSession: (session: Session) => void;
  deleteSession: (id: string) => void;

  addMessage: (sessionId: string, message: Message) => void;
  clearMessages: (sessionId: string) => void;

  setIsTyping: (typing: boolean) => void;
  toggleSidebar: () => void;

  setMemories: (memories: Memory[]) => void;
  setMemorySearchQuery: (query: string) => void;
}

export const useStore = create<AppState>()(
  persist(
    (set, get) => ({
      // 初始状态
      sessions: [],
      currentSessionId: null,
      messages: {},
      isTyping: false,
      sidebarOpen: true,
      memories: [],
      memorySearchQuery: '',

      // 会话操作
      setSessions: (sessions) => set({ sessions }),

      setCurrentSession: (id) => set({ currentSessionId: id }),

      addSession: (session) =>
        set((state) => ({
          sessions: [session, ...state.sessions],
        })),

      deleteSession: (id) =>
        set((state) => ({
          sessions: state.sessions.filter((s) => s.id !== id),
          messages: { ...state.messages, [id]: undefined },
        })),

      // 消息操作
      addMessage: (sessionId, message) =>
        set((state) => ({
          messages: {
            ...state.messages,
            [sessionId]: [...(state.messages[sessionId] || []), message],
          },
        })),

      clearMessages: (sessionId) =>
        set((state) => ({
          messages: { ...state.messages, [sessionId]: [] },
        })),

      // UI 操作
      setIsTyping: (typing) => set({ isTyping: typing }),

      toggleSidebar: () =>
        set((state) => ({
          sidebarOpen: !state.sidebarOpen,
        })),

      // 记忆操作
      setMemories: (memories) => set({ memories }),

      setMemorySearchQuery: (query) => set({ memorySearchQuery: query }),
    }),
    {
      name: 'sage-storage',
      partialize: (state) => ({
        // 只持久化必要的数据
        sessions: state.sessions,
      }),
    },
  ),
);
```

### 9.4.2 Hooks

```typescript
// hooks/useChat.ts
import { useCallback } from 'react';
import { useStore } from '../lib/store';
import { invoke } from '@tauri-apps/api/core';

export function useChat() {
  const { currentSessionId, addMessage, setIsTyping, messages } = useStore();

  const sendMessage = useCallback(
    async (content: string) => {
      if (!currentSessionId) return;

      // 添加用户消息
      const userMessage = {
        id: crypto.randomUUID(),
        session_id: currentSessionId,
        role: 'user' as const,
        content,
        created_at: Date.now(),
      };
      addMessage(currentSessionId, userMessage);

      // 设置 typing 状态
      setIsTyping(true);

      try {
        // 调用后端
        const response = await invoke<string>('agent_chat', {
          sessionId: currentSessionId,
          message: content,
        });

        // 添加助手消息
        const assistantMessage = {
          id: crypto.randomUUID(),
          session_id: currentSessionId,
          role: 'assistant' as const,
          content: response,
          created_at: Date.now(),
        };
        addMessage(currentSessionId, assistantMessage);
      } catch (error) {
        console.error('Chat error:', error);

        // 添加错误消息
        const errorMessage = {
          id: crypto.randomUUID(),
          session_id: currentSessionId,
          role: 'assistant' as const,
          content: `错误: ${error}`,
          created_at: Date.now(),
        };
        addMessage(currentSessionId, errorMessage);
      } finally {
        setIsTyping(false);
      }
    },
    [currentSessionId, addMessage, setIsTyping],
  );

  const interrupt = useCallback(async () => {
    try {
      await invoke('interrupt_agent');
    } catch (error) {
      console.error('Interrupt error:', error);
    }
  }, []);

  return {
    sendMessage,
    interrupt,
    messages: currentSessionId ? messages[currentSessionId] || [] : [],
  };
}
```

---

## 9.5 路由

### 9.5.1 路由定义

```tsx
// App.tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Chat } from './pages/Chat';
import { Memory } from './pages/Memory';
import { Settings } from './pages/Settings';
import { Skills } from './pages/Skills';
import { Layout } from './components/layout/Layout';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route path="chat" element={<Chat />} />
          <Route path="memory" element={<Memory />} />
          <Route path="skills" element={<Skills />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

---

## 9.6 国际化

### 9.6.1 i18n 配置

```typescript
// i18n/index.ts
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zhCN from './locales/zh-CN.json';
import en from './locales/en.json';

i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { translation: zhCN },
    en: { translation: en },
  },
  lng: 'zh-CN',
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false,
  },
});

export default i18n;
```

### 9.6.2 示例翻译

```json
// zh-CN.json
{
  "app": {
    "name": "Sage",
    "tagline": "你的记忆型 AI 助手"
  },
  "chat": {
    "placeholder": "输入消息...",
    "send": "发送",
    "newChat": "新对话"
  },
  "memory": {
    "title": "记忆浏览器",
    "search": "搜索记忆",
    "noMemory": "暂无记忆"
  },
  "settings": {
    "title": "设置",
    "model": "模型设置",
    "theme": "主题"
  }
}
```

---

## 配置存储（2026-06-22 起）

Sage 前端配置（settings / theme / current_session_id）从 localStorage 迁移至
后端 SQLite `preferences` 表。三处 localStorage 仍保留作为离线缓存兜底。

**加载策略**：后端 → localStorage → DEFAULT
**写入策略**：同步写 cache + 异步推后端（5s 超时）
**迁移策略**：首次后端无值 + localStorage 有数据 + 未标记 → 自动上传

相关代码：
- 前端：`src/entities/setting/storage.ts`、`src/entities/theme/storage.ts`、
  `src/entities/session/storage.ts`、`src/shared/api/settingsClient.ts`
- 后端：`backend/data/settings_repo.py`、`backend/api/hex_routes.py`
- Electron IPC：`electron/commands.ts`（4 条新路由）

---

_文档版本: v1.0_
