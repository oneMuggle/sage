import { useState, useEffect, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';

import faq from '../../content/help/faq.md?raw';
import gettingStarted from '../../content/help/getting-started.md?raw';
import troubleshooting from '../../content/help/troubleshooting.md?raw';
import { HelpSidebar } from '../../widgets/help/HelpSidebar';
import type { HelpItem } from '../../widgets/help/HelpSidebar';

// Import built-in help content

const BUILTIN_CONTENT: Record<string, string> = {
  'getting-started': gettingStarted,
  faq: faq,
  troubleshooting: troubleshooting,
};

// Help directory structure
const HELP_ITEMS: HelpItem[] = [
  {
    id: 'getting-started',
    title: '快速上手',
    type: 'builtin',
  },
  {
    id: 'core-features',
    title: '核心功能',
    type: 'builtin',
    children: [
      { id: 'chat', title: '对话', type: 'builtin' },
      { id: 'memory', title: '记忆', type: 'builtin' },
      { id: 'skills', title: '技能', type: 'builtin' },
    ],
  },
  {
    id: 'advanced-features',
    title: '高级功能',
    type: 'builtin',
    children: [
      { id: 'office', title: 'Office', type: 'builtin' },
      { id: 'orchestration', title: '编排', type: 'builtin' },
    ],
  },
  {
    id: 'faq',
    title: '常见问题',
    type: 'builtin',
  },
  {
    id: 'troubleshooting',
    title: '故障排除',
    type: 'builtin',
  },
  {
    id: 'user-manual-separator',
    title: '更多文档',
    type: 'builtin',
  },
  {
    id: 'desktop-usage',
    title: '桌面使用',
    type: 'user-manual',
    filename: '01-desktop.md',
  },
  {
    id: 'memory-system',
    title: '记忆系统',
    type: 'user-manual',
    filename: '04-memory.md',
  },
  {
    id: 'office-docs',
    title: 'Office',
    type: 'user-manual',
    filename: '09-office.md',
  },
];

export function HelpTab() {
  const [activeItem, setActiveItem] = useState('getting-started');
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load content based on active item
  useEffect(() => {
    const item = findItemById(HELP_ITEMS, activeItem);
    if (!item) return;

    if (item.type === 'builtin') {
      // Built-in content is already imported
      const builtinContent = BUILTIN_CONTENT[activeItem];
      if (builtinContent) {
        setContent(builtinContent);
        setError(null);
      } else {
        setContent(`# ${item.title}\n\n内容正在编写中...`);
        setError(null);
      }
    } else if (item.type === 'user-manual' && item.filename) {
      // Load from user-manual via IPC
      setLoading(true);
      setError(null);
      window.helpAPI
        ?.readUserManual(item.filename)
        .then((loadedContent) => {
          setContent(loadedContent);
        })
        .catch((err) => {
          setError(`无法加载帮助内容: ${err instanceof Error ? err.message : String(err)}`);
          setContent(
            '# 内容加载失败\n\n请稍后重试或查看[在线文档](https://github.com/oneMuggle/sage/tree/main/docs/user-manual)',
          );
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [activeItem]);

  // Memoize rendered markdown to avoid re-parsing
  const renderedContent = useMemo(() => {
    if (loading) {
      return <div className="animate-pulse text-text-secondary">加载中...</div>;
    }
    if (error) {
      return <div className="text-error">{error}</div>;
    }
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeKatex]}
        components={{
          h1: ({ children }) => <h1 className="text-2xl font-bold mb-4 text-text">{children}</h1>,
          h2: ({ children }) => (
            <h2 className="text-xl font-semibold mb-3 mt-6 text-text">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-lg font-medium mb-2 mt-4 text-text">{children}</h3>
          ),
          p: ({ children }) => <p className="mb-4 text-text leading-relaxed">{children}</p>,
          code: ({ className, children }) => {
            const isInline = !className;
            return isInline ? (
              <code className="px-1.5 py-0.5 rounded bg-bg-subtle border border-border text-xs font-mono text-text-secondary">
                {children}
              </code>
            ) : (
              <pre className="mb-4 p-4 rounded-radius-sm bg-bg-subtle border border-border overflow-x-auto">
                <code className="text-xs font-mono text-text">{children}</code>
              </pre>
            );
          },
          ul: ({ children }) => (
            <ul className="mb-4 list-disc list-inside space-y-1 text-text">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-4 list-decimal list-inside space-y-1 text-text">{children}</ol>
          ),
          li: ({ children }) => <li className="text-text">{children}</li>,
          a: ({ href, children }) => (
            <a
              href={href}
              className="text-primary hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="mb-4 pl-4 border-l-4 border-primary/30 italic text-text-secondary">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="mb-4 overflow-x-auto">
              <table className="min-w-full border border-border rounded-radius-sm">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-bg-subtle border-b border-border">{children}</thead>
          ),
          tbody: ({ children }) => <tbody className="divide-y divide-border">{children}</tbody>,
          tr: ({ children }) => <tr className="hover:bg-bg-hover">{children}</tr>,
          th: ({ children }) => (
            <th className="px-4 py-2 text-left text-xs font-semibold text-text-secondary">
              {children}
            </th>
          ),
          td: ({ children }) => <td className="px-4 py-2 text-sm text-text">{children}</td>,
        }}
      >
        {content}
      </ReactMarkdown>
    );
  }, [content, loading, error]);

  return (
    <div className="flex h-full">
      <HelpSidebar items={HELP_ITEMS} activeItem={activeItem} onItemClick={setActiveItem} />
      <div className="flex-1 overflow-y-auto px-8 py-6" data-testid="help-content">
        <div className="max-w-3xl">{renderedContent}</div>
      </div>
    </div>
  );
}

// Helper function to find item by ID recursively
function findItemById(items: HelpItem[], id: string): HelpItem | null {
  for (const item of items) {
    if (item.id === id) return item;
    if (item.children) {
      const found = findItemById(item.children, id);
      if (found) return found;
    }
  }
  return null;
}
