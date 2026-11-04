// src/widgets/chat/MermaidBlock.tsx
//
// U7' (对标增强第五轮批次 A, docs/plans/2026-09-08_coding-agent-parity-round5.md):
// ```mermaid 代码块渲染为 SVG 图表。mermaid 经动态 import() 独立 chunk，
// 不打开含图表的会话不加载，主包体积零增长（round4 批次 F 评审结论见 §5）。
//
// 2026-11-04 (rich-preview-rendering Task 3): 交互逻辑抽到 MermaidDiagram
// （拖拽平移 / Ctrl+滚轮 / 源码切换 / SVG 导出），本文件只负责
// 「跟随应用主题」这一层，审计函数保持导出契约不变（向后兼容）。
// - 主题跟随 ThemeProvider（html.dark → 'dark'，否则 'default'）；
// - 渲染失败（语法错误/超大图）回退 ShikiCodeBlock 源码展示，不静默吞错。

import { useEffect, useState } from 'react';

import { MermaidDiagram } from './MermaidDiagram';

export type { MermaidBlockAuditInput } from './MermaidDiagram';
// eslint-disable-next-line react-refresh/only-export-components
export { formatMermaidBlockAuditJson, formatMermaidBlockAuditSnapshot } from './MermaidDiagram';

function currentTheme(): 'dark' | 'default' {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'default';
}

export function MermaidBlock({ code }: { code: string }) {
  // 2026-09-13 P0: 主题响应式 — 此前 effect 依赖只有 [code]，会话中途切换
  // 亮/暗主题时图表不跟随（下次 code 变化才重渲染）。观察 html class 变化
  // (ThemeProvider 双轨切 .dark + data-theme) 触发重渲染。
  const [theme, setTheme] = useState<'dark' | 'default'>(currentTheme);

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(currentTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  return <MermaidDiagram code={code} theme={theme} />;
}
