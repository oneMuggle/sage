// 代码块语言 → 渲染器分发注册表。
// 目前仅 mermaid / html 需要富渲染，其余语言交给 Shiki 默认高亮。
// 匹配时忽略大小写与首尾空白，避免 ```HTML / ```Mermaid 退化成纯文本。

export type CodeFenceRendererKind = 'mermaid' | 'html' | 'default';

const LANGUAGE_RENDERERS: Record<string, Exclude<CodeFenceRendererKind, 'default'>> = {
  mermaid: 'mermaid',
  html: 'html',
};

export function resolveCodeFenceRenderer(language?: string | null): CodeFenceRendererKind {
  const key = (language ?? '').trim().toLowerCase();
  return LANGUAGE_RENDERERS[key] ?? 'default';
}
