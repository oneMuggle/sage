// src/widgets/chat/MermaidBlock.tsx
//
// U7' (对标增强第五轮批次 A, docs/plans/2026-09-08_coding-agent-parity-round5.md):
// ```mermaid 代码块渲染为 SVG 图表。mermaid 经动态 import() 独立 chunk，
// 不打开含图表的会话不加载，主包体积零增长（round4 批次 F 评审结论见 §5）。
//
// 设计:
// - 模块级单例加载 mermaid（initialize 基线配置一次，render 前按当前主题重设）；
// - 主题跟随 ThemeProvider（html.dark → 'dark'，否则 'default'）；
// - 渲染失败（语法错误/超大图）回退 ShikiCodeBlock 源码展示，不静默吞错。

import { useEffect, useState } from 'react';

import { ShikiCodeBlock } from './ShikiCodeBlock';

type MermaidApi = import('mermaid').default;

let mermaidPromise: Promise<MermaidApi> | null = null;

function currentTheme(): 'dark' | 'default' {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'default';
}

async function loadMermaid(): Promise<MermaidApi> {
  mermaidPromise ??= import('mermaid').then((mod) => {
    mod.default.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      maxTextSize: 50000,
      maxEdges: 500,
    });
    return mod.default;
  });
  return mermaidPromise;
}

/** render id 全局自增（同页多图/重渲染不冲突） */
let renderSeq = 0;

export function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const id = `sage-mermaid-${++renderSeq}`;
    loadMermaid()
      .then(async (mermaid) => {
        // 每次渲染前按当前主题重设（dark/light 切换后新渲染即跟随）
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: currentTheme(),
          maxTextSize: 50000,
          maxEdges: 500,
        });
        const { svg: out } = await mermaid.render(id, code);
        if (cancelled) return;
        setSvg(out);
        setFailed(false);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (failed) {
    return (
      <div data-testid="mermaid-fallback">
        <div className="text-xs text-amber-600 dark:text-amber-400 mb-1">
          Mermaid 图表渲染失败，显示源码
        </div>
        <ShikiCodeBlock language="mermaid">{code}</ShikiCodeBlock>
      </div>
    );
  }
  if (svg === null) {
    return <div data-testid="mermaid-loading" className="text-xs text-muted p-2">渲染图表…</div>;
  }
  return (
    // mermaid SVG 自带配色，容器给白底保证 dark 模式下可读；strict 模式下
    // 输出无脚本，dangerouslySetInnerHTML 安全
    <div
      data-testid="mermaid-figure"
      className="my-2 p-2 overflow-x-auto rounded border border-border bg-white"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
