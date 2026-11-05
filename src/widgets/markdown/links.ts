/**
 * Markdown 链接判定 —— 从 MessageMarkdownParts 抽出（2026-11-02）。
 *
 * 独立成模块是为避免 widgets/markdown 反向依赖 widgets/chat（循环导入风险），
 * 同时让 feat/file-reference-preview 的本地文件链接判定在所有渲染场景
 * （消息 / 产物 / Wiki）中行为一致。
 *
 * 判定规则：非外链协议、非协议相对、且含有路径分隔符或已知文件扩展名。
 */

/** 本地文件扩展名白名单（与 feat/file-reference-preview 对齐） */
const FILE_EXT_RE =
  /\.(md|markdown|mdx|txt|log|py|js|ts|tsx|jsx|rs|go|java|c|cpp|h|hpp|cs|rb|php|swift|kt|sh|bash|zsh|ps1|sql|html?|css|scss|yaml|yml|toml|ini|xml|png|jpe?g|gif|webp|svg|bmp|csv|tsv|json|pdf|docx|xlsx|pptx)$/i;

/** 非文件协议的 scheme —— 命中即外链 */
const NON_FILE_SCHEME_RE = /^(https?:|mailto:|tel:|#|data:|blob:|sage-file:)/i;

/**
 * 安全解码 URI 中的 percent-encoding。
 *
 * mdast-util-to-hast 在 link 节点转 hast 时调 normalizeUri（来自
 * micromark-util-sanitize-uri），把中文等非 ASCII 字符做了 percent-encoding
 * （如 "算法.md" → "%E7%AE%97%E6%B3%95.md"）。点击回调必须用解码后的原始
 * 路径传给后端，否则后端按字面值找不到文件 → 404。
 *
 * try/catch 兜底畸形 URI（裸 "%" 等），失败时原样返回。
 */
export function safeDecodeUri(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * 判定一个 href 是否指向本地/工作区文件路径。
 * 用于把 markdown 中的文件引用渲染成"点击打开右栏预览"的按钮。
 *
 * normalizeUri 可能已把路径编码（如 "%E7%AE%97"），先解码再判定
 * 保证扩展名正则能正确匹配（极端情况 .md → %2Emd 也能识别）。
 */
export function isLocalFilePathHref(href: string | undefined | null): href is string {
  const raw = (href ?? '').trim();
  if (!raw) return false;
  const value = safeDecodeUri(raw);
  if (NON_FILE_SCHEME_RE.test(value)) return false;
  if (value.startsWith('//')) return false;
  return /[\\/]/.test(value) || FILE_EXT_RE.test(value);
}
