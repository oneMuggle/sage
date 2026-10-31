/**
 * Pure animation selection for the pet renderer.
 *
 * The renderer keeps the actual video element; this module only decides
 * which clip to play for a snapshot and what the bubble says.
 */

import type { PetSnapshotBridge } from '../../shared/types/electron-api';

export interface PetPack {
  id: string;
  name: string;
  version: string;
  license: string;
  source: string;
  canvas: { width: number; height: number };
  anchor: { x: number; y: number };
  actions: Record<string, string[]>;
}

export interface AnimationChoice {
  file: string;
  loop: boolean;
}

const LOOPING_ACTIONS = new Set([
  'idle',
  'thinking',
  'acting',
  'observing',
  'retry',
  'waiting',
  'sleeping',
]);

export function resolveAnimation(
  snapshot: Pick<PetSnapshotBridge, 'action' | 'detail'>,
  pack: PetPack | null,
): AnimationChoice | null {
  if (!pack) return null;
  const detailKey =
    snapshot.action === 'acting' && snapshot.detail ? `acting_${snapshot.detail}` : null;
  const keys = [
    detailKey,
    snapshot.action === 'sleeping' ? 'sleep_loop' : snapshot.action,
    'idle',
  ].filter((key): key is string => Boolean(key));
  for (const key of keys) {
    const files = pack.actions[key];
    if (files && files.length > 0) {
      return { file: files[0], loop: LOOPING_ACTIONS.has(snapshot.action) };
    }
  }
  return null;
}

export function resolveInteraction(pack: PetPack | null, key: string): AnimationChoice | null {
  const files = pack?.actions[key];
  if (!files || files.length === 0) return null;
  return { file: files[0], loop: false };
}

const BUBBLE_TEXT: Record<string, { zh: string; en: string }> = {
  waiting: { zh: '有个操作等你确认', en: 'Waiting for your approval' },
  error: { zh: '出错了，来看看', en: 'Something went wrong' },
  done: { zh: '干完啦', en: 'All done' },
  retry: { zh: '再试一次…', en: 'Retrying…' },
  tool_bash: { zh: '正在跑命令', en: 'Running a command' },
  tool_edit: { zh: '正在改代码', en: 'Editing code' },
  tool_read: { zh: '正在翻文件', en: 'Reading files' },
  tool_web: { zh: '正在上网查', en: 'Searching the web' },
  tool_mcp: { zh: '正在用外部工具', en: 'Using an external tool' },
  tool_office: { zh: '正在写文档', en: 'Working on a document' },
  tool_other: { zh: '正在干活', en: 'Working' },
  subagent: { zh: '子任务进行中', en: 'Sub-agent is working' },
  todo: { zh: '更新了待办', en: 'Updated the todo list' },
};

export function bubbleText(key: string | null): string | null {
  if (!key) return null;
  const text = BUBBLE_TEXT[key];
  if (!text) return null;
  const zh = typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('zh');
  return zh ? text.zh : text.en;
}
