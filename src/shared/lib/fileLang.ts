/**
 * fileLang — 文件路径 → Shiki 语言名（right-panel R6）。
 *
 * 从 ArtifactViewer 的 EXT_LANG 表上抬为共享模块：变更面板"预览"视图
 * 与产物预览共用同一份扩展名映射。未识别的扩展名返回 undefined，
 * 调用方回落纯文本（ShikiCodeBlock 对未预装语言也会静默回落 text）。
 */

const EXT_LANG: Record<string, string> = {
  py: 'python',
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  json: 'json',
  jsonc: 'json',
  md: 'markdown',
  markdown: 'markdown',
  sh: 'bash',
  bash: 'bash',
  rs: 'rust',
  go: 'go',
  java: 'java',
  kt: 'kotlin',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  hpp: 'cpp',
  cs: 'csharp',
  rb: 'ruby',
  php: 'php',
  sql: 'sql',
  yaml: 'yaml',
  yml: 'yaml',
  toml: 'toml',
  css: 'css',
  scss: 'scss',
  html: 'html',
  xml: 'xml',
  vue: 'vue',
  swift: 'swift',
  dart: 'dart',
};

/** 按扩展名推断 Shiki 语言；无扩展名/未识别返回 undefined（回落纯文本） */
export function langFromPath(path: string): string | undefined {
  const name = path.split(/[\\/]/).pop() ?? '';
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : '';
  return EXT_LANG[ext];
}
