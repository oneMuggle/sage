/**
 * P2-a (2026-09-20): 运行中发送的三种投递通道。
 *
 * 对标结论（2026-09 调研 VS Code / Cursor / Codex CLI / Claude Code）：主流应用
 * 全部让用户**显式**选择通道（VS Code 把三项放在 Send 下拉里，Cursor 用修饰键
 * 区分），没有一家让模型猜意图；被抱怨的也不是"默认选错"而是"生效时机不透明"
 * （Claude Code 的注入发生在"下一个 LLM 暂停"，用户以为是任务结束后）。
 * 所以这里每个通道都自带时机描述文案。
 */

import type { TranslationKey } from '../../shared/lib/i18n';

export type DeliveryMode = 'steer' | 'queue' | 'interrupt';

export interface DeliveryModeMeta {
  mode: DeliveryMode;
  /** 下拉项主标签 i18n key */
  labelKey: TranslationKey;
  /** 时机说明 i18n key（必须写清"什么时候生效"） */
  hintKey: TranslationKey;
  /** 忙时主按钮的短标签 i18n key */
  shortKey: TranslationKey;
  /** 快捷键提示（非 i18n，纯符号） */
  shortcut: string;
}

/** 会话忙时的默认通道：插话（不打断当前动作，只在迭代边界并入上下文）。 */
export const DEFAULT_DELIVERY_MODE: DeliveryMode = 'steer';

export const DELIVERY_MODES: readonly DeliveryModeMeta[] = [
  {
    mode: 'steer',
    labelKey: 'chat.delivery_steer',
    hintKey: 'chat.delivery_steer_hint',
    shortKey: 'chat.delivery_steer_short',
    shortcut: 'Enter',
  },
  {
    mode: 'queue',
    labelKey: 'chat.delivery_queue',
    hintKey: 'chat.delivery_queue_hint',
    shortKey: 'chat.delivery_queue_short',
    shortcut: 'Alt+Enter',
  },
  {
    mode: 'interrupt',
    labelKey: 'chat.delivery_interrupt',
    hintKey: 'chat.delivery_interrupt_hint',
    shortKey: 'chat.delivery_interrupt_short',
    // Windows/Linux 显示 Ctrl，macOS 显示 ⌘（两者都映射到 interrupt）。
    shortcut: 'Ctrl+Enter',
  },
] as const;

export function deliveryModeMeta(mode: DeliveryMode): DeliveryModeMeta {
  const found = DELIVERY_MODES.find((m) => m.mode === mode);
  return found ?? DELIVERY_MODES[0];
}

/**
 * 把 keydown 修饰键翻译成显式通道；返回 null 表示走默认通道。
 * Alt/Ctrl 与 ⌘ 都算显式修饰（macOS 上 ⌘+Enter 更符合肌肉记忆），Shift+Enter
 * 是换行、由调用方提前拦掉，不归这里管。
 */
export function deliveryModeFromKey(event: {
  altKey?: boolean;
  ctrlKey?: boolean;
  metaKey?: boolean;
}): DeliveryMode | null {
  if (event.altKey) return 'queue';
  if (event.ctrlKey || event.metaKey) return 'interrupt';
  return null;
}
