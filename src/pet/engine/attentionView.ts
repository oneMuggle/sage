/**
 * Overlay badge derived from the global attention payload.
 *
 * The badge summarises every session that needs the user, while the sprite
 * itself follows one session (focus / urgent / pinned). Keeping the two
 * separate means a busy background session is never hidden just because the
 * focused session is quiet.
 */

import type { PetAttentionBridge } from '../../shared/types/electron-api';

import { statusGlyph, statusLabel } from './labels';

export interface AttentionView {
  glyph: string;
  count: number | null;
  alert: boolean;
  title: string;
}

export function attentionView(
  action: string,
  detail: string | null,
  toolName: string | null,
  attention: PetAttentionBridge | undefined,
): AttentionView {
  const needsYou = attention?.needsYou ?? 0;
  const base = statusLabel(action, detail, toolName);
  if (!attention || needsYou <= 0) {
    return { glyph: statusGlyph(action), count: null, alert: false, title: base };
  }
  const parts = [`${needsYou} 个待处理`];
  if (attention.running > 0) parts.push(`${attention.running} 个进行中`);
  if (attention.failed > 0) parts.push(`${attention.failed} 个出错`);
  return {
    glyph: statusGlyph(action),
    count: Math.min(99, needsYou),
    alert: true,
    title: `${base} · ${parts.join(' · ')}`,
  };
}

/** Needs-you session ids that were not present in the previous payload. */
export function newNeedsYouSessions(
  previous: ReadonlySet<string>,
  ids: readonly string[],
): string[] {
  return ids.filter((id) => !previous.has(id));
}
