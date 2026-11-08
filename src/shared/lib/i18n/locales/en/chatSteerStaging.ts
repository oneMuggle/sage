/**
 * Steer staging area (PendingSteerPanel) — 2026-11-07
 *
 * Split out: chatAndSider sits at the 800-line architecture ratchet
 * (en 810 / zh 811). en.ts merges this via `...enChatSteerStaging`.
 */

export const enChatSteerStaging = {
  'chat.steer_pending_title': 'Pending delivery',
  'chat.steer_pending_hint': 'Read at the next boundary — click X to recall it first',
  'chat.steer_pending_cancel': 'Recall steer',
} as const;
