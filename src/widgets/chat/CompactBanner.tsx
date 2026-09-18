import { Package } from 'lucide-react';

import { useI18n } from '../../shared/lib/i18n';

/** 上下文压缩的统计三元组（与后端 compact_info 列同形）。 */
export interface CompactInfo {
  before: number;
  after: number;
  removed: number;
}

/** 把 `{key}` 占位符替换成对应值（与 Chat.tsx 的 fill 同语义）。 */
function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  );
}

/**
 * R38: 压缩通知横幅。
 *
 * 两类渲染位置共用同一组件，保证口径一致：
 * - 重新载入历史时，续接摘要行（role=assistant）气泡**上方**的横幅；
 * - 流进行中合成的即时通知（role=system）—— 单行居中呈现。
 *
 * 文案完全由 `info` 推导，**不读 message.content** —— 续接行的 content
 * 是 LLM 写的摘要正文，与统计无关。
 */
export function CompactBanner({ info }: { info: CompactInfo }) {
  const { t } = useI18n();
  const text = fill(t('chat.compact_success'), {
    before: info.before,
    after: info.after,
    removed: info.removed,
  });
  return (
    <div
      data-testid="compact-banner"
      className="flex items-center gap-1.5 px-3 py-1.5 my-2 rounded-radius-sm bg-bg-subtle border border-border text-xs text-text-secondary"
    >
      <Package className="w-3 h-3 text-muted flex-shrink-0" />
      <span>{text}</span>
    </div>
  );
}
