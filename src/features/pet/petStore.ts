// src/features/pet/petStore.ts
//
// 桌面宠物 P1（docs/plans/2026-09-18_desktop-pet-design.md）——
// 把「会话流式状态 / 等待确认 / 任务板进度」聚合归约成八态 PetState，
// 供 widgets/pet/PetDock 渲染。数据源全部来自既有 store，本 feature
// 不新增任何 IPC / 后端链路。
//
// 设计对齐 rightPanelStore：module-singleton zustand + 手工 localStorage
// 持久化（pet-enabled / pet-selected）。celebrate/failed 是「沿触发 + TTL
// 衰减」的瞬时态（useChat 在流结束时调 triggerFlash），不落盘。

import { create } from 'zustand';

import type { AgentState } from '../../shared/api/types';
import type { SessionStreamSlots } from '../send-message/chatStreamStore';

/** 宠物八态（优先级从高到低归约，见 computePetState） */
export const PET_STATES = [
  'attention',
  'thinking',
  'working',
  'celebrate',
  'failed',
  'reporting',
  'idle',
  'sleeping',
] as const;
export type PetState = (typeof PET_STATES)[number];

/** 完成/失败庆祝窗口：到点自动衰减回 idle */
export const FLASH_TTL_MS: Record<'celebrate' | 'failed', number> = {
  celebrate: 8_000,
  failed: 10_000,
};
/** idle 持续该时长后进入 sleeping */
export const SLEEP_AFTER_MS = 5 * 60_000;

export interface PetFlash {
  kind: 'celebrate' | 'failed';
  sessionId: string;
  at: number;
}

/** 单会话投影到宠物视角的最小事实 */
export interface PetSessionLite {
  /** 该会话有活跃流（含 content_delta 等） */
  busy: boolean;
  thinking: boolean;
  working: boolean;
  /** 任务板存在且仍有 running/queued 子任务 */
  reporting: boolean;
}

export interface PetComputeInput {
  /** sessionId → lite（调用方负责剔除 '__btw__' 等伪会话） */
  sessions: Record<string, PetSessionLite>;
  /** 有挂起权限请求/提问的会话（到达序） */
  attentionSessionIds: string[];
  flash: PetFlash | null;
  now: number;
  /** 最近一次 busy→idle 翻转时刻（sleeping 判定基准） */
  idleSince: number;
}

export interface PetSnapshot {
  state: PetState;
  /** 点击宠物时优先跳转的会话 */
  sessionId: string | null;
}

const THINKING_STATES: ReadonlySet<AgentState> = new Set([
  'thinking',
  'reasoning',
  'reasoning_delta',
  'reasoning_final',
]);
const WORKING_STATES: ReadonlySet<AgentState> = new Set([
  'acting',
  'observing',
  'content_delta',
  'suspended',
  'step_done',
]);

export function toPetSessionLite(slots: SessionStreamSlots): PetSessionLite {
  const state = slots.streaming?.state ?? null;
  const progress = slots.taskBoard?.progress;
  return {
    busy: slots.streaming != null,
    thinking: state != null && THINKING_STATES.has(state),
    working: slots.streamingToolCalls.length > 0 || (state != null && WORKING_STATES.has(state)),
    reporting:
      slots.taskBoard != null &&
      slots.streaming != null &&
      ((progress ? progress.running + progress.queued > 0 : true) ||
        Object.values(slots.taskBoard.statuses ?? {}).some(
          (st) => st.status === 'running' || st.status === 'queued',
        )),
  };
}

/** 纯函数归约，now 注入便于测试（优先级见 docs/plans §2.1 表）。 */
export function computePetState(input: PetComputeInput): PetSnapshot {
  const { sessions, attentionSessionIds, flash, now, idleSince } = input;

  if (attentionSessionIds.length > 0) {
    return { state: 'attention', sessionId: attentionSessionIds[0] };
  }
  if (flash && now - flash.at < FLASH_TTL_MS[flash.kind]) {
    return { state: flash.kind, sessionId: flash.sessionId };
  }
  for (const [id, lite] of Object.entries(sessions)) {
    if (lite.thinking) return { state: 'thinking', sessionId: id };
  }
  for (const [id, lite] of Object.entries(sessions)) {
    if (lite.working) return { state: 'working', sessionId: id };
  }
  for (const [id, lite] of Object.entries(sessions)) {
    if (lite.reporting) return { state: 'reporting', sessionId: id };
  }
  const anyBusy = Object.values(sessions).some((lite) => lite.busy);
  if (anyBusy) return { state: 'idle', sessionId: null };
  if (now - idleSince >= SLEEP_AFTER_MS) return { state: 'sleeping', sessionId: null };
  return { state: 'idle', sessionId: null };
}

const ENABLED_KEY = 'pet-enabled';
const SELECTED_KEY = 'pet-selected';

function loadEnabled(): boolean {
  try {
    return localStorage.getItem(ENABLED_KEY) === '1';
  } catch {
    return false;
  }
}

function loadSelected(): string {
  try {
    return localStorage.getItem(SELECTED_KEY) ?? '';
  } catch {
    return '';
  }
}

interface PetStoreState {
  enabled: boolean;
  petId: string;
  flash: PetFlash | null;
  setEnabled: (v: boolean) => void;
  setPetId: (id: string) => void;
  triggerFlash: (kind: 'celebrate' | 'failed', sessionId: string) => void;
}

let flashTimer: ReturnType<typeof setTimeout> | null = null;

export const usePetStore = create<PetStoreState>((set) => ({
  enabled: loadEnabled(),
  petId: loadSelected(),
  flash: null,

  setEnabled: (enabled) => {
    try {
      localStorage.setItem(ENABLED_KEY, enabled ? '1' : '0');
    } catch {
      // localStorage 不可用（隐私模式等），静默容忍
    }
    set({ enabled });
  },

  setPetId: (petId) => {
    try {
      localStorage.setItem(SELECTED_KEY, petId);
    } catch {
      // 同上
    }
    set({ petId });
  },

  triggerFlash: (kind, sessionId) => {
    if (flashTimer != null) clearTimeout(flashTimer);
    set({ flash: { kind, sessionId, at: Date.now() } });
    flashTimer = setTimeout(() => {
      flashTimer = null;
      set({ flash: null });
    }, FLASH_TTL_MS[kind]);
  },
}));
