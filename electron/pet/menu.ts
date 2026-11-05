/**
 * Pet overlay context menu.
 *
 * Kept out of controller.ts so the controller stays below the 800-line gate.
 */

import { Menu, type MenuItemConstructorOptions } from 'electron';

import type {
  PetBubbleMode,
  PetConfig,
  PetFollowMode,
  PetRenderConfig,
  PetSize,
  PetSnapshot,
  PetTempo,
} from './types';

const SIZE_LABELS: Record<PetSize, string> = {
  mini: '迷你',
  small: '小',
  medium: '中',
  large: '大',
  huge: '特大',
};

const TEMPO_LABELS: Record<PetTempo, string> = {
  quiet: '安静',
  standard: '标准',
  lively: '活泼',
};

const BUBBLE_LABELS: Record<PetBubbleMode, string> = {
  important: '仅重要状态',
  always: '常驻',
  off: '隐藏',
};

export interface PetMenuContext {
  config: PetRenderConfig;
  snapshot: PetSnapshot;
  setPetSize: (size: PetSize) => void;
  setGlobal: (patch: Partial<PetConfig>) => void;
  setFollow: (patch: { followMode: PetFollowMode; pinnedSessionId: string | null }) => void;
  openSession: (sessionId: string | null) => void;
  cycleFocus: () => void;
  resetPosition: () => void;
  openSettings: () => void;
  hide: () => void;
  disable: () => void;
}

export function buildPetMenu(ctx: PetMenuContext): Menu {
  const { config, snapshot } = ctx;
  const pet = config.pets.find((item) => item.id === config.petId);
  const followMode = pet?.followMode ?? 'focus';
  const pinnedSessionId = pet?.pinnedSessionId ?? null;
  const template: MenuItemConstructorOptions[] = [
    {
      label: '大小',
      submenu: (Object.keys(SIZE_LABELS) as PetSize[]).map((size) => ({
        label: SIZE_LABELS[size],
        type: 'radio',
        checked: config.size === size,
        click: () => ctx.setPetSize(size),
      })),
    },
    {
      label: '节奏',
      submenu: (Object.keys(TEMPO_LABELS) as PetTempo[]).map((tempo) => ({
        label: TEMPO_LABELS[tempo],
        type: 'radio',
        checked: config.tempo === tempo,
        click: () => ctx.setGlobal({ tempo }),
      })),
    },
    {
      label: '减少动态',
      type: 'checkbox',
      checked: config.reduceMotion,
      click: () => ctx.setGlobal({ reduceMotion: !config.reduceMotion }),
    },
    {
      label: '气泡',
      submenu: (Object.keys(BUBBLE_LABELS) as PetBubbleMode[]).map((bubbleMode) => ({
        label: BUBBLE_LABELS[bubbleMode],
        type: 'radio',
        checked: config.bubbleMode === bubbleMode,
        click: () => ctx.setGlobal({ bubbleMode }),
      })),
    },
    { type: 'separator' },
    {
      label: '跟随方式',
      submenu: [
        {
          label: '跟随焦点会话',
          type: 'radio',
          checked: followMode === 'focus',
          click: () => ctx.setFollow({ followMode: 'focus', pinnedSessionId }),
        },
        {
          label: '紧急优先',
          type: 'radio',
          checked: followMode === 'urgent',
          click: () => ctx.setFollow({ followMode: 'urgent', pinnedSessionId }),
        },
        {
          label: '钉住当前会话',
          type: 'radio',
          checked: followMode === 'pinned',
          enabled: Boolean(snapshot.sessionId),
          click: () => ctx.setFollow({ followMode: 'pinned', pinnedSessionId: snapshot.sessionId }),
        },
      ],
    },
    {
      label: '下一个待处理',
      enabled: snapshot.attention.needsYouSessionIds.length > 0,
      click: () => ctx.cycleFocus(),
    },
    { type: 'separator' },
    {
      label: '打开会话',
      enabled: Boolean(snapshot.sessionId),
      click: () => ctx.openSession(snapshot.sessionId),
    },
    { label: '回到初始位置', click: () => ctx.resetPosition() },
    { label: '宠物设置…', click: () => ctx.openSettings() },
    { label: '本次隐藏', click: () => ctx.hide() },
    { type: 'separator' },
    { label: '关闭桌宠', click: () => ctx.disable() },
  ];
  return Menu.buildFromTemplate(template);
}
