/**
 * 极简 ICU-lite 占位符替换：
 *   formatMessage('Hello, {name}!', { name: 'Alice' }) === 'Hello, Alice!'
 * 不支持嵌套、复数、select、escape；保持最小 surface。
 *
 * 防御行为：
 *   - template 为 null/undefined → 返回 ''
 *   - 占位符 key 不在 params 中 → 保留 '{key}' 字面（开发期易识别）
 */

const PLACEHOLDER_RE = /\{(\w+)\}/g;

export function formatMessage(
  template: string | null | undefined,
  params: Record<string, string | number>,
): string {
  if (template == null) {
    return '';
  }
  return template.replace(PLACEHOLDER_RE, (_match, key: string) => {
    const v = params[key];
    return v == null ? `{${key}}` : String(v);
  });
}
