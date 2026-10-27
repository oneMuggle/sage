import { ChevronDown, Send } from 'lucide-react';

import {
  DELIVERY_MODES,
  DEFAULT_DELIVERY_MODE,
  deliveryModeMeta,
} from '../../features/send-message/deliveryMode';
import type { DeliveryMode } from '../../features/send-message/deliveryMode';
import { useI18n } from '../../shared/lib/i18n';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '../../shared/ui/DropdownMenu/DropdownMenu';

export interface DeliverySendGroupProps {
  sendDisabled: boolean;
  onSubmit: () => void;
  onSubmitWithMode: (mode: DeliveryMode) => void;
}

/**
 * P2-a 分体发送按钮：调研结论是"时序不透明"才是排队功能被投诉的
 * 主因，因此默认通道一键可发，另外两条通道必须在界面上写清楚
 * "什么时候生效"。
 */
export function DeliverySendGroup({
  sendDisabled,
  onSubmit,
  onSubmitWithMode,
}: DeliverySendGroupProps) {
  const { t } = useI18n();
  return (
    <div
      data-testid="delivery-group"
      className="flex items-stretch rounded-radius-sm overflow-hidden"
    >
      <button
        type="button"
        data-testid="chat-send"
        onClick={onSubmit}
        disabled={sendDisabled}
        title={t(deliveryModeMeta(DEFAULT_DELIVERY_MODE).hintKey)}
        className="h-9 pl-4 pr-3 bg-primary text-text-inverse border-none text-sm font-medium cursor-pointer flex items-center gap-1.5 hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {t(deliveryModeMeta(DEFAULT_DELIVERY_MODE).shortKey)}
        <Send className="w-3.5 h-3.5" />
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            data-testid="chat-delivery-menu"
            aria-label={t('chat.delivery_menu')}
            title={t('chat.delivery_menu')}
            disabled={sendDisabled}
            className="h-9 px-1.5 bg-primary text-text-inverse border-none border-l border-text-inverse/25 cursor-pointer flex items-center hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors rounded-radius-sm"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-[16rem]">
          <DropdownMenuLabel>{t('chat.delivery_menu')}</DropdownMenuLabel>
          {DELIVERY_MODES.map((m) => (
            <DropdownMenuItem
              key={m.mode}
              data-testid={`chat-delivery-${m.mode}`}
              onSelect={() => onSubmitWithMode(m.mode)}
              className="items-start"
            >
              <span className="flex flex-col gap-0.5 py-0.5">
                <span className="flex items-center justify-between gap-3 font-medium">
                  {t(m.labelKey)}
                  <kbd className="text-ui-xs text-muted">{m.shortcut}</kbd>
                </span>
                <span className="text-ui-2xs font-normal text-muted">{t(m.hintKey)}</span>
              </span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
