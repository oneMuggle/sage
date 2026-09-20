import { AlertTriangle, ExternalLink, Globe, KeyRound, Settings } from 'lucide-react';

import { useI18n } from '../../shared/lib/i18n';
import type { BlockedAction } from '../../shared/lib/store';

/** blockReason → i18n 键映射（与后端 web_tool.py BLOCK_REASON_* 枚举对齐） */
const REASON_I18N_KEYS: Record<string, string> = {
  antibot_cf: 'chat.blocked.reason.antibot_cf',
  antibot_other: 'chat.blocked.reason.antibot_other',
  login_wall: 'chat.blocked.reason.login_wall',
  http_4xx: 'chat.blocked.reason.http_4xx',
  http_5xx: 'chat.blocked.reason.http_5xx',
  timeout: 'chat.blocked.reason.timeout',
  dns: 'chat.blocked.reason.dns',
  render: 'chat.blocked.reason.render',
  generic: 'chat.blocked.reason.generic',
};

/** action id → 图标 */
const ACTION_ICONS: Record<string, React.ReactNode> = {
  open_browser: <Globe className="w-3.5 h-3.5" />,
  configure_credentials: <KeyRound className="w-3.5 h-3.5" />,
  configure_proxy: <Settings className="w-3.5 h-3.5" />,
  view_docs: <ExternalLink className="w-3.5 h-3.5" />,
};

/** action id → 按钮样式 */
const ACTION_STYLES: Record<string, string> = {
  open_browser: 'border-primary/40 bg-primary/10 text-primary hover:bg-primary/20',
  configure_credentials: 'border-border bg-surface hover:bg-bg-hover text-text-secondary',
  configure_proxy: 'border-border bg-surface hover:bg-bg-hover text-text-secondary',
  view_docs: 'border-border bg-surface hover:bg-bg-hover text-text-secondary',
};

interface BlockedCardProps {
  /** 拦截原因枚举（与后端 BLOCK_REASON_* 一致） */
  blockReason: string;
  /** 被拦截的目标 URL */
  blockedUrl?: string;
  /** 后端建议的动作按钮 */
  suggestedActions?: BlockedAction[];
  /** 可读错误文案（已从信封提取） */
  errorMessage?: string;
  /** 动作回调 —— 由 Chat 层处理实际语义（发消息 / 跳设置 / 开浏览器） */
  onAction?: (action: BlockedAction) => void;
}

/**
 * R19-W1: 网页访问拦截可视化卡片
 *
 * 当 web_fetch 被反爬/登录墙/网络错误拦截时，后端返回结构化 block payload，
 * 前端渲染此卡片代替原始错误文本，提供可点击的动作按钮引导用户自助解决。
 */
export function BlockedCard({
  blockReason,
  blockedUrl,
  suggestedActions,
  errorMessage,
  onAction,
}: BlockedCardProps) {
  const { t } = useI18n();

  const reasonKey = REASON_I18N_KEYS[blockReason] ?? 'chat.blocked.reason.generic';
  const reasonLabel = t(reasonKey as Parameters<typeof t>[0]);

  return (
    <div
      className="mx-2 mb-2 rounded-radius-sm border border-warning/40 bg-warning/5 overflow-hidden"
      data-testid="blocked-card"
      data-block-reason={blockReason}
    >
      {/* 标题栏 */}
      <div className="flex items-center gap-2 px-3 py-2 bg-warning/10 border-b border-warning/30">
        <AlertTriangle className="w-4 h-4 text-warning shrink-0" />
        <span className="text-[13px] font-medium text-warning">{t('chat.blocked.title')}</span>
        <span className="ml-auto text-[11px] px-1.5 py-0.5 rounded bg-warning/15 text-warning/80 font-mono">
          {blockReason}
        </span>
      </div>

      {/* 内容区 */}
      <div className="px-3 py-2.5 flex flex-col gap-2">
        {/* 目标 URL */}
        {blockedUrl && (
          <div className="flex items-start gap-2 text-[12px]">
            <span className="text-muted shrink-0">{t('chat.blocked.target')}</span>
            <span className="font-mono text-text-secondary break-all" title={blockedUrl}>
              {blockedUrl}
            </span>
          </div>
        )}

        {/* 原因说明 */}
        <div className="text-[12px] text-text-secondary leading-relaxed">{reasonLabel}</div>

        {/* 后端给出的错误详情（可选） */}
        {errorMessage && (
          <div className="text-[11px] text-muted font-mono bg-bg-subtle/60 rounded px-2 py-1 break-all">
            {errorMessage}
          </div>
        )}

        {/* 建议动作按钮 */}
        {suggestedActions && suggestedActions.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {suggestedActions.map((action, idx) => {
              const icon = ACTION_ICONS[action.action] ?? null;
              const style =
                ACTION_STYLES[action.action] ??
                'border-border bg-surface hover:bg-bg-hover text-text-secondary';
              return (
                <button
                  key={`${action.action}-${idx}`}
                  type="button"
                  data-testid={`blocked-action-${action.action}`}
                  onClick={() => onAction?.(action)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-[12px] border transition-colors ${style}`}
                >
                  {icon}
                  <span>{action.label}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
