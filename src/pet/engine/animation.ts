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
  variant = 0,
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
      const index = Math.abs(Math.floor(variant)) % files.length;
      const loop = LOOPING_ACTIONS.has(snapshot.action) && snapshot.action !== 'idle';
      return { file: files[index], loop };
    }
  }
  return null;
}

export function resolveInteraction(
  pack: PetPack | null,
  key: string,
  random: () => number = Math.random,
): AnimationChoice | null {
  const files = pack?.actions[key];
  if (!files || files.length === 0) return null;
  const index = Math.abs(Math.floor(random() * files.length)) % files.length;
  return { file: files[index], loop: false };
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
  progress: { zh: '任务进度更新', en: 'Task progress updated' },
};

export interface BubbleContext {
  toolName?: string | null;
  sessionTitle?: string | null;
  showSession?: boolean;
  todoDone?: number;
  todoTotal?: number;
}

function shortTitle(title: string | null | undefined): string {
  const trimmed = title?.trim();
  if (!trimmed) return '';
  return trimmed.length > 18 ? `${trimmed.slice(0, 18)}…` : trimmed;
}

export function bubbleText(key: string | null, ctx: BubbleContext = {}): string | null {
  if (!key) return null;
  const zh = typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('zh');
  const suffix = ctx.showSession ? shortTitle(ctx.sessionTitle) : '';
  const withSuffix = (base: string): string => (suffix ? `${base} · ${suffix}` : base);
  if (key === 'waiting' && ctx.toolName) {
    return zh ? withSuffix(`等待审批：${ctx.toolName}`) : withSuffix(`Approval: ${ctx.toolName}`);
  }
  if (key === 'error' && ctx.toolName) {
    return zh ? withSuffix(`出错了：${ctx.toolName}`) : withSuffix(`Error: ${ctx.toolName}`);
  }
  if (key === 'todo' && ctx.todoTotal) {
    const done = ctx.todoDone ?? 0;
    return zh
      ? withSuffix(`待办 ${done}/${ctx.todoTotal}`)
      : withSuffix(`Todos ${done}/${ctx.todoTotal}`);
  }
  if (key === 'progress' && ctx.todoTotal) {
    const done = ctx.todoDone ?? 0;
    return zh
      ? withSuffix(`步骤 ${done}/${ctx.todoTotal}`)
      : withSuffix(`Steps ${done}/${ctx.todoTotal}`);
  }
  const text = BUBBLE_TEXT[key];
  if (!text) return null;
  return withSuffix(zh ? text.zh : text.en);
}
