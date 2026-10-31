/**
 * In-app pet corner dock.
 *
 * Shown when displayMode is `in-app` or `both`. Uses the same snapshots and
 * pet pack as the desktop overlay, but renders inside the main window so it
 * works without a transparent OS window (Win7 / remote desktop).
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { bubbleText, resolveAnimation } from '../../pet/engine/animation';
import { statusGlyph, statusLabel } from '../../pet/engine/labels';
import { safePlay } from '../../pet/engine/media';
import { packFor } from '../../pet/engine/packs';
import type { PetConfigBridge, PetSnapshotBridge } from '../../shared/types/electron-api';

const WIDTHS: Record<string, number> = {
  mini: 96,
  small: 120,
  medium: 150,
  large: 190,
  huge: 230,
};

const EMPTY_SNAPSHOT: PetSnapshotBridge = {
  action: 'idle',
  detail: null,
  sessionId: null,
  sessionTitle: null,
  toolName: null,
  bubbleKey: null,
  bubbleKind: null,
  todoDone: 0,
  todoTotal: 0,
  todoActive: null,
  progressKind: null,
  contextUsed: null,
  contextMax: null,
  lastTerminalAction: null,
  lastTerminalAt: null,
  patCount: 0,
  bondDays: 1,
  activeSessions: 0,
  sessions: [],
  updatedAt: 0,
};

const DEFAULT_CONFIG: PetConfigBridge = {
  version: 1,
  enabled: false,
  displayMode: 'desktop',
  size: 'medium',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: false,
  compatibilityMode: 'auto',
  petPack: 'dafeiyu',
  followActiveSession: true,
};

function badgeClass(action: string): string {
  switch (action) {
    case 'waiting':
      return 'border-amber-400/80 text-amber-300 animate-pulse';
    case 'error':
      return 'border-red-500/80 text-red-300';
    case 'done':
      return 'border-green-500/80 text-green-300';
    case 'acting':
      return 'border-teal-400/80 text-teal-300 animate-pulse';
    case 'thinking':
      return 'border-blue-400/80 text-blue-300 animate-pulse';
    case 'retry':
      return 'border-purple-400/80 text-purple-300';
    default:
      return 'border-slate-500/70 text-slate-300';
  }
}

export function InAppPet(): JSX.Element | null {
  const [snapshot, setSnapshot] = useState<PetSnapshotBridge>(EMPTY_SNAPSHOT);
  const [config, setConfig] = useState<PetConfigBridge>(DEFAULT_CONFIG);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const currentFileRef = useRef('');

  const pet = typeof window !== 'undefined' ? window.electronAPI?.pet : undefined;

  useEffect(() => {
    if (!pet) return undefined;
    let alive = true;
    void pet.getConfig().then((value) => {
      if (alive) setConfig(value);
    });
    void pet.getState().then((value) => {
      if (alive) setSnapshot(value);
    });
    const offState = pet.onState((value) => {
      if (alive) setSnapshot(value);
    });
    const offConfig = pet.onConfig((value) => {
      if (alive) setConfig(value);
    });
    return () => {
      alive = false;
      offState();
      offConfig();
    };
  }, [pet]);

  const pack = useMemo(() => packFor(config.petPack), [config.petPack]);
  const choice = useMemo(() => {
    const action = snapshot.action;
    const detail = snapshot.detail;
    if (!pack) return null;
    if (action === 'idle' && pack.actions.idle?.length) {
      return { file: pack.actions.idle[0], loop: true };
    }
    return resolveAnimation({ action, detail }, pack, 0);
  }, [snapshot.action, snapshot.detail, pack]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !choice) return;
    const src = encodeURI(`./pet/${config.petPack}/${choice.file}`);
    if (currentFileRef.current !== src) {
      currentFileRef.current = src;
      video.src = src;
      video.loop = choice.loop;
      video.muted = true;
      safePlay(video);
    } else {
      video.loop = choice.loop;
      if (video.paused) safePlay(video);
    }
    if (config.reduceMotion) {
      const stop = (): void => {
        video.pause();
        try {
          video.currentTime = 0;
        } catch {
          // Metadata may not be ready yet.
        }
      };
      if (video.readyState >= 2) stop();
      else video.addEventListener('loadeddata', stop, { once: true });
    }
  }, [choice, config.petPack, config.reduceMotion, config.enabled, config.displayMode]);

  const visible =
    config.enabled && (config.displayMode === 'in-app' || config.displayMode === 'both');
  if (!visible) return null;

  const width = WIDTHS[config.size] ?? 150;
  const height = Math.round((width * 360) / 640);
  const title = statusLabel(snapshot.action, snapshot.detail, snapshot.toolName);
  const bubble = bubbleText(snapshot.bubbleKey, {
    toolName: snapshot.toolName,
    sessionTitle: snapshot.sessionTitle,
    showSession: config.showSessionTitle,
    todoDone: snapshot.todoDone,
    todoTotal: snapshot.todoTotal,
  });
  const targetSession = snapshot.sessionId ?? snapshot.sessions[0]?.sessionId ?? null;

  return (
    <div
      className="pointer-events-none fixed bottom-20 right-4 z-30 flex flex-col items-end"
      data-testid="in-app-pet"
    >
      {bubble ? (
        <div className="mb-1 max-w-[220px] truncate rounded-lg border border-slate-500/40 bg-slate-900/90 px-2 py-1 text-xs text-slate-100 shadow">
          {bubble}
        </div>
      ) : null}
      <button
        type="button"
        className="pointer-events-auto relative block border-0 bg-transparent p-0"
        title={title}
        aria-label={title}
        onClick={() => {
          if (targetSession) pet?.openSession(targetSession);
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          pet?.openSettings();
        }}
      >
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          preload="auto"
          className="block select-none"
          style={{ width, height }}
        />
        <span
          className={`absolute right-0 top-0 flex h-5 w-5 items-center justify-center rounded-full border bg-slate-900/80 text-ui-2xs font-bold ${badgeClass(
            snapshot.action,
          )}`}
        >
          {statusGlyph(snapshot.action)}
        </span>
      </button>
    </div>
  );
}
