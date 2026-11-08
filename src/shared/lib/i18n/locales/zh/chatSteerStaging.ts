/**
 * 插话暂存区（PendingSteerPanel） —— 2026-11-07
 *
 * 独立成模块：chatAndSider 已触及 800 行架构棘轮（en 810 / zh 811），
 * 新键放这里避免继续膨胀；zh.ts 通过 `...zhChatSteerStaging` 展开合并。
 */

export const zhChatSteerStaging = {
  'chat.steer_pending_title': '待生效',
  'chat.steer_pending_hint': 'AI 在下一个边界读取；点 X 可在送达前撤回',
  'chat.steer_pending_cancel': '撤回插话',
} as const;
