import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { PetConfigBridge, PetSnapshotBridge } from '../shared/types/electron-api';

import { PetPanel } from './PetPanel';
import { bubbleText, resolveAnimation, resolveInteraction } from './engine/animation';
import { isChinese, statusLabel } from './engine/labels';
import { packFor } from './engine/packs';
import { playSound, primeAudio } from './engine/sounds';
import { idleDelayMs } from './engine/tempo';

const LONG_PRESS_MS = 550;
const CLICK_DELAY_MS = 240;
const ANGER_WINDOW_MS = 2000;
const ANGER_CLICKS = 5;

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
  enabled: true,
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

interface PlaybackOverride {
  file: string;
  loop: boolean;
}

interface LocalBubble {
  text: string;
  kind: 'info' | 'success' | 'error';
}

function statusGlyph(action: string): string {
  switch (action) {
    case 'waiting':
    case 'error':
      return '!';
    case 'done':
      return '✓';
    case 'acting':
      return '▶';
    case 'thinking':
      return '…';
    case 'retry':
      return '↻';
    case 'observing':
      return '◇';
    case 'sleeping':
      return 'z';
    default:
      return '·';
  }
}

export function PetApp(): JSX.Element {
  const [snapshot, setSnapshot] = useState<PetSnapshotBridge>(EMPTY_SNAPSHOT);
  const [config, setConfig] = useState<PetConfigBridge>(DEFAULT_CONFIG);
  const [override, setOverride] = useState<PlaybackOverride | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [localBubble, setLocalBubble] = useState<LocalBubble | null>(null);
  const [idleVariant, setIdleVariant] = useState(0);
  const [idleResting, setIdleResting] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const dragRef = useRef({
    down: false,
    moved: false,
    longPressFired: false,
    startX: 0,
    startY: 0,
  });
  const currentFileRef = useRef('');
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clickTimes = useRef<number[]>([]);
  const suppressClickUntil = useRef(0);
  const lastActionRef = useRef(snapshot.action);
  const lastSoundActionRef = useRef('');

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
    pet.ready();
    return () => {
      alive = false;
      offState();
      offConfig();
    };
  }, [pet]);

  useEffect(() => {
    if (lastActionRef.current === snapshot.action) return;
    lastActionRef.current = snapshot.action;
    setOverride(null);
    setLocalBubble(null);
    setIdleVariant((variant) => variant + 1);
    setIdleResting(false);
    if (idleTimer.current) {
      clearTimeout(idleTimer.current);
      idleTimer.current = null;
    }
  }, [snapshot.action]);

  useEffect(() => {
    const action = snapshot.action;
    if (action === lastSoundActionRef.current) return;
    lastSoundActionRef.current = action;
    const kind =
      action === 'waiting'
        ? 'waiting'
        : action === 'error'
          ? 'error'
          : action === 'done'
            ? 'done'
            : null;
    if (kind && config.soundScenes[kind]) playSound(kind);
  }, [snapshot.action, config.soundScenes]);

  useEffect(() => {
    if (!localBubble) return undefined;
    const timer = setTimeout(() => setLocalBubble(null), 2500);
    return () => clearTimeout(timer);
  }, [localBubble]);

  useEffect(
    () => () => {
      if (pressTimer.current) clearTimeout(pressTimer.current);
      if (clickTimer.current) clearTimeout(clickTimer.current);
      if (idleTimer.current) clearTimeout(idleTimer.current);
    },
    [],
  );

  const pack = useMemo(() => packFor(config.petPack), [config.petPack]);

  const choice = useMemo(() => {
    if (override) return override;
    if (snapshot.action === 'idle' && idleResting && pack?.actions.idle?.length) {
      return { file: pack.actions.idle[0], loop: true };
    }
    return resolveAnimation(snapshot, pack, idleVariant);
  }, [override, snapshot, pack, idleVariant, idleResting]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !choice) return;
    const src = encodeURI(`./pet/${config.petPack}/${choice.file}`);
    if (currentFileRef.current !== src) {
      currentFileRef.current = src;
      video.src = src;
      video.loop = choice.loop;
      video.muted = true;
      void video.play().catch(() => undefined);
    } else {
      video.loop = choice.loop;
      if (video.paused) void video.play().catch(() => undefined);
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
  }, [choice, config.petPack, config.reduceMotion]);

  const togglePanel = useCallback(() => {
    setPanelOpen((open) => {
      const next = !open;
      pet?.setPanel(next);
      return next;
    });
  }, [pet]);

  const closePanel = useCallback(() => {
    setPanelOpen(false);
    pet?.setPanel(false);
  }, [pet]);

  const openSession = useCallback(
    (sessionId: string | null) => {
      if (sessionId) pet?.openSession(sessionId);
    },
    [pet],
  );

  const openSettings = useCallback(() => {
    pet?.openSettings();
  }, [pet]);

  const clearClickTimer = useCallback(() => {
    if (clickTimer.current) {
      clearTimeout(clickTimer.current);
      clickTimer.current = null;
    }
  }, []);

  const triggerClick = useCallback(() => {
    const click = resolveInteraction(pack, 'click');
    if (click) setOverride(click);
    togglePanel();
  }, [pack, togglePanel]);

  const triggerPat = useCallback(() => {
    const pat = resolveInteraction(pack, 'pat');
    if (pat) setOverride(pat);
    setLocalBubble({
      text: isChinese() ? '被摸头了～' : 'Head pat!',
      kind: 'success',
    });
    pet?.pat();
  }, [pack, pet]);

  const triggerAngry = useCallback(() => {
    const angry = resolveInteraction(pack, 'angry');
    if (angry) setOverride(angry);
    setLocalBubble({
      text: isChinese() ? '别戳啦！' : 'Stop poking!',
      kind: 'error',
    });
    suppressClickUntil.current = Date.now() + 1500;
  }, [pack]);

  const handleShortClick = useCallback(() => {
    const now = Date.now();
    clickTimes.current = [
      ...clickTimes.current.filter((time) => now - time <= ANGER_WINDOW_MS),
      now,
    ];
    if (clickTimes.current.length >= ANGER_CLICKS) {
      clickTimes.current = [];
      clearClickTimer();
      triggerAngry();
      return;
    }
    clearClickTimer();
    clickTimer.current = setTimeout(() => {
      clickTimer.current = null;
      triggerClick();
    }, CLICK_DELAY_MS);
  }, [clearClickTimer, triggerAngry, triggerClick]);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return;
    primeAudio();
    dragRef.current = {
      down: true,
      moved: false,
      longPressFired: false,
      startX: event.clientX,
      startY: event.clientY,
    };
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Synthetic or already-released pointers may not support capture.
    }
    pet?.dragStart();
    if (pressTimer.current) clearTimeout(pressTimer.current);
    pressTimer.current = setTimeout(() => {
      pressTimer.current = null;
      const drag = dragRef.current;
      if (!drag.down || drag.moved) return;
      drag.longPressFired = true;
      triggerPat();
    }, LONG_PRESS_MS);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>): void => {
    const drag = dragRef.current;
    if (!drag.down) return;
    if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) > 4) {
      drag.moved = true;
      if (pressTimer.current) {
        clearTimeout(pressTimer.current);
        pressTimer.current = null;
      }
    }
    if (drag.moved) pet?.dragMove();
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>): void => {
    const drag = dragRef.current;
    if (!drag.down) return;
    drag.down = false;
    if (pressTimer.current) {
      clearTimeout(pressTimer.current);
      pressTimer.current = null;
    }
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // Pointer may already be released.
    }
    pet?.dragEnd();
    if (drag.moved || drag.longPressFired) return;
    if (Date.now() < suppressClickUntil.current) return;
    handleShortClick();
  };

  const handleEnded = (): void => {
    if (override) {
      setOverride(null);
      if (localBubble) setLocalBubble(null);
      return;
    }
    if (localBubble) setLocalBubble(null);
    if (snapshot.action === 'idle' && !config.reduceMotion) {
      setIdleResting(true);
      if (idleTimer.current) clearTimeout(idleTimer.current);
      idleTimer.current = setTimeout(() => {
        idleTimer.current = null;
        setIdleResting(false);
        setIdleVariant((variant) => variant + 1);
      }, idleDelayMs(config.tempo));
    }
  };

  const stateBubble = bubbleText(snapshot.bubbleKey, {
    toolName: snapshot.toolName,
    sessionTitle: snapshot.sessionTitle,
    showSession: config.showSessionTitle,
    todoDone: snapshot.todoDone,
    todoTotal: snapshot.todoTotal,
  });
  const bubble = localBubble?.text ?? stateBubble;
  const bubbleKind = localBubble?.kind ?? snapshot.bubbleKind;
  const bubbleClass = bubbleKind ? `pet-bubble pet-bubble-${bubbleKind}` : 'pet-bubble';
  const statusTitle = statusLabel(snapshot.action, snapshot.detail, snapshot.toolName);

  return (
    <div className="pet-root" data-panel={panelOpen ? 'open' : 'closed'}>
      {panelOpen ? (
        <PetPanel
          snapshot={snapshot}
          config={config}
          onClose={closePanel}
          onOpenSession={openSession}
          onOpenSettings={openSettings}
        />
      ) : null}
      <div
        className="pet-stage"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onContextMenu={(event) => {
          event.preventDefault();
          pet?.showMenu();
        }}
      >
        <div
          className={`pet-badge pet-badge-${snapshot.action}`}
          title={statusTitle}
          aria-label={statusTitle}
        >
          {statusGlyph(snapshot.action)}
        </div>
        {bubble ? <div className={bubbleClass}>{bubble}</div> : null}
        <video
          ref={videoRef}
          className="pet-video"
          autoPlay
          muted
          playsInline
          preload="auto"
          onEnded={handleEnded}
        />
      </div>
    </div>
  );
}
