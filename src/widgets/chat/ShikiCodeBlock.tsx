/**
 * Shiki 代码块 — 替代 react-syntax-highlighter
 *
 * - 使用 shiki (VSCode 同款引擎) 进行语法高亮
 * - 支持亮/暗主题自动切换
 * - 延迟加载 highlighter (首次渲染时初始化)
 */

import { ArrowDown, Check, Copy, WrapText } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';

/** 全局 highlighter 单例 */
let highlighterPromise: Promise<import('shiki/core').HighlighterCore> | null = null;

// R24-D6: shiki 静态 import 会把整包(~1MB)拖进主 chunk —— 即便聊天首屏
// 一个代码块都没有。改动态 import(): 包体独立成 chunk, 首个代码块渲染
// 时才加载；类型仍走 import('shiki') 静态类型引用。
//
// 续 R24-D6: 上一版 `import('shiki')` 拉的是 full bundle —— 它内部对全部
// ~350 种语法做动态注册, Rollup 无法 tree-shake, 于是下面这 18 种声明形同
// 虚设: 构建仍产出 70 个 grammar chunk / 4.7MB, 含 emacs-lisp(762KB)、
// wolfram(262KB)、vue-vine(190KB) 等永远不会被加载的死重。
//
// 改走 shiki/core + 逐个精确 import: 只有下面显式列出的语法/主题会进产物,
// 且每个仍是独立 chunk(按需加载语义不变)。新增语言 = 在 LANGS 里加一行。
function getHighlighter(): Promise<import('shiki/core').HighlighterCore> {
  if (!highlighterPromise) {
    highlighterPromise = Promise.all([
      import('shiki/core'),
      import('shiki/engine/oniguruma'),
    ]).then(([{ createHighlighterCore }, { createOnigurumaEngine }]) =>
      createHighlighterCore({
        themes: [
          import('@shikijs/themes/github-dark'),
          import('@shikijs/themes/github-light'),
        ],
        langs: [
          import('@shikijs/langs/javascript'),
          import('@shikijs/langs/typescript'),
          import('@shikijs/langs/python'),
          import('@shikijs/langs/rust'),
          import('@shikijs/langs/go'),
          import('@shikijs/langs/java'),
          import('@shikijs/langs/cpp'),
          import('@shikijs/langs/c'),
          import('@shikijs/langs/html'),
          import('@shikijs/langs/css'),
          import('@shikijs/langs/json'),
          import('@shikijs/langs/yaml'),
          import('@shikijs/langs/toml'),
          import('@shikijs/langs/markdown'),
          import('@shikijs/langs/bash'),
          import('@shikijs/langs/sql'),
          import('@shikijs/langs/docker'),
          import('@shikijs/langs/diff'),
        ],
        engine: createOnigurumaEngine(import('shiki/wasm')),
      }),
    );
  }
  return highlighterPromise;
}

interface ShikiCodeBlockProps {
  language?: string;
  children: string;
}

/** P2: 超过该行数的代码块默认折叠（对标 Cherry Studio 长代码折叠） */
const FOLD_THRESHOLD_LINES = 30;

export function ShikiCodeBlock({ language, children }: ShikiCodeBlockProps) {
  const { t } = useI18n();
  const [highlightedHtml, setHighlightedHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const langRef = useRef(language);
  langRef.current = language;
  // P2 (UI 优化方案 2026-09-13): 长代码折叠 + 自动换行切换
  const [wrapped, setWrapped] = useState(false);
  const lineCount = useMemo(() => children.replace(/\n$/, '').split('\n').length, [children]);
  const [folded, setFolded] = useState(() => lineCount > FOLD_THRESHOLD_LINES);

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
        <div className="flex items-center gap-1">
          {/* P2: 自动换行切换 —— 长行代码在宽屏上免横向滚动 */}
          <button
            onClick={() => setWrapped((v) => !v)}
            title={t('codeBlock.toggleWrap')}
            aria-label={t('codeBlock.toggleWrap')}
            aria-pressed={wrapped}
            className={
              'flex items-center gap-1 px-2 py-0.5 rounded transition-colors ' +
              (wrapped
                ? 'bg-white/15 text-white'
                : 'opacity-0 group-hover:opacity-100 hover:bg-white/10 text-gray-300 hover:text-white')
            }
          >
            <WrapText className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleCopy}
            className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 px-2 py-0.5 rounded hover:bg-white/10 text-gray-300 hover:text-white"
            title={t('codeBlock.copy')}
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-green-400" />
                <span>{t('codeBlock.copied')}</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>{t('codeBlock.copy')}</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* 代码区域 —— 折叠时长代码限高 + 底部渐隐 + 展开按钮 */}
      <div className={folded ? 'relative max-h-64 overflow-hidden' : undefined}>
        {highlightedHtml ? (
          <div
            className={
              'shiki-code overflow-x-auto text-xs leading-relaxed ' +
              (wrapped ? '[&_code]:whitespace-pre-wrap [&_code]:break-words' : '')
            }
            style={{ margin: 0 }}
            dangerouslySetInnerHTML={{ __html: highlightedHtml }}
          />
        ) : (
          <pre
            className={
              'bg-[#282c34] text-gray-300 p-3 text-xs leading-relaxed overflow-x-auto rounded-b-md ' +
              (wrapped ? 'whitespace-pre-wrap break-words' : '')
            }
          >
            <code>{children.replace(/\n$/, '')}</code>
          </pre>
        )}
        {folded && (
          <div className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-[#282c34] to-transparent pointer-events-none" />
        )}
        {folded && (
          <button
            onClick={() => setFolded(false)}
            data-testid="code-expand"
            className="absolute inset-x-0 bottom-2 mx-auto w-fit flex items-center gap-1 px-3 py-1 rounded-full bg-white/10 hover:bg-white/20 text-gray-200 text-xs backdrop-blur-sm transition-colors"
          >
            <ArrowDown className="w-3 h-3" />
            {t('codeBlock.expandLines').replace('{n}', String(lineCount))}
          </button>
        )}
      </div>
    </div>
  );
}
