// src/features/pet/usePetSnapshot.ts
//
// 把各聚合 store 喂给 computePetState 的活体 hook：
// - chatStreamStore.sessions → PetSessionLite 投影（剔除 '__btw__' 伪会话）
// - permission/question 的 pendingBySession → attention 会话列表
// - petStore.flash → celebrate/failed 窗口
// - busy→idle 翻转记录 idleSince；idle 满 SLEEP_AFTER_MS 用一次性 timer
//   重算进入 sleeping。

import { useEffect, useMemo, useRef, useState } from 'react';

import { usePermissionState } from '../../entities/permission/permissionState';
import { useQuestionState } from '../../entities/question/questionState';
import { useChatStreamStore } from '../send-message/chatStreamStore';

import {
  SLEEP_AFTER_MS,
  computePetState,
  toPetSessionLite,
  usePetStore,
  type PetSessionLite,
  type PetSnapshot,
} from './petStore';

/** /btw 侧问伪会话不进宠物（useChat askBtw 专用槽位） */
const PSEUDO_SESSIONS: ReadonlySet<string> = new Set(['__btw__']);

export function usePetSnapshot(): PetSnapshot {
  const streamSessions = useChatStreamStore((s) => s.sessions);
  const pendingPermissions = usePermissionState((s) => s.pendingBySession);
  const pendingQuestions = useQuestionState((s) => s.pendingBySession);
  const flash = usePetStore((s) => s.flash);

  const lites = useMemo(() => {
    const out: Record<string, PetSessionLite> = {};
    for (const [id, slots] of Object.entries(streamSessions)) {
      if (PSEUDO_SESSIONS.has(id)) continue;
      const lite = toPetSessionLite(slots);
      if (lite.busy) out[id] = lite;
    }
    return out;
  }, [streamSessions]);

  const attentionSessionIds = useMemo(() => {
    const ids: string[] = [];
    for (const id of Object.keys(pendingPermissions)) {
      if (!PSEUDO_SESSIONS.has(id) && !ids.includes(id)) ids.push(id);
    }
    for (const id of Object.keys(pendingQuestions)) {
      if (!PSEUDO_SESSIONS.has(id) && !ids.includes(id)) ids.push(id);
    }
    return ids;
  }, [pendingPermissions, pendingQuestions]);

  const busy =
    Object.values(lites).some((lite) => lite.busy) || attentionSessionIds.length > 0;

  const idleSinceRef = useRef<number>(Date.now());
  const prevBusyRef = useRef<boolean>(busy);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (busy === prevBusyRef.current) return;
    if (!busy) idleSinceRef.current = Date.now();
    prevBusyRef.current = busy;
  }, [busy]);

  // 全 idle 时挂一次性 timer，到点重算以进入 sleeping
  useEffect(() => {
    if (busy) return;
    const remaining = SLEEP_AFTER_MS - (Date.now() - idleSinceRef.current);
    if (remaining <= 0) {
      setTick((n) => n + 1);
      return;
    }
    const timer = setTimeout(() => setTick((n) => n + 1), remaining);
    return () => clearTimeout(timer);
  }, [busy, lites, flash, tick]);

  return useMemo(() => {
    void tick; // sleeping 判定依赖 timer 到点重算 now（tick 本身无值语义）
    return computePetState({
      sessions: lites,
      attentionSessionIds,
      flash,
      now: Date.now(),
      idleSince: idleSinceRef.current,
    });
    // tick: sleeping 到点重算的依赖
  }, [lites, attentionSessionIds, flash, tick]);
}
