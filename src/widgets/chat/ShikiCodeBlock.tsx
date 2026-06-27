/**
 * Shiki 代码块 — 替代 react-syntax-highlighter
 *
 * - 使用 shiki (VSCode 同款引擎) 进行语法高亮
 * - 支持亮/暗主题自动切换
 * - 延迟加载 highlighter (首次渲染时初始化)
 */

import { Copy, Check } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { createHighlighter, type Highlighter } from 'shiki';

/** 全局 highlighter 单例 */
let highlighterPromise: Promise<Highlighter> | null = null;

function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      themes: ['github-dark', 'github-light'],
      langs: [
        'javascript',
        'typescript',
        'python',
        'rust',
        'go',
        'java',
        'cpp',
        'c',
        'html',
        'css',
        'json',
        'yaml',
        'toml',
        'markdown',
        'bash',
        'sql',
        'dockerfile',
        'diff',
      ],
    });
  }
  return highlighterPromise;
}

interface ShikiCodeBlockProps {
  language?: string;
  children: string;
}

export function ShikiCodeBlock({ language, children }: ShikiCodeBlockProps) {
  const [highlightedHtml, setHighlightedHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const langRef = useRef(language);
  langRef.current = language;

  useEffect(() => {
    let cancelled = false;
    const code = children.replace(/\n$/, '');

    getHighlighter()
      .then((hl) => {
        if (cancelled) return;
        const lang = language && hl.getLoadedLanguages().includes(language) ? language : 'text';
        const html = hl.codeToHtml(code, {
          lang,
          themes: { dark: 'github-dark', light: 'github-light' },
          defaultColor: false,
        });
        setHighlightedHtml(html);
      })
      .catch(() => {
        // fallback: 不设置高亮
      });

    return () => {
      cancelled = true;
    };
  }, [children, language]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(children);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative group my-2">
      {/* 头部栏 */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#282c34] rounded-t-md text-xs text-gray-300">
        <span className="font-mono">{language || 'text'}</span>
        <button
          onClick={handleCopy}
          className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 px-2 py-0.5 rounded hover:bg-white/10 text-gray-300 hover:text-white"
          title="复制代码"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-green-400" />
              <span>已复制</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>复制</span>
            </>
          )}
        </button>
      </div>

      {/* 代码区域 */}
      {highlightedHtml ? (
        <div
          className="shiki-code overflow-x-auto text-xs leading-relaxed"
          style={{ margin: 0 }}
          dangerouslySetInnerHTML={{ __html: highlightedHtml }}
        />
      ) : (
        <pre className="bg-[#282c34] text-gray-300 p-3 text-xs leading-relaxed overflow-x-auto rounded-b-md">
          <code>{children.replace(/\n$/, '')}</code>
        </pre>
      )}
    </div>
  );
}
