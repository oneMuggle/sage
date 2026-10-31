import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { PetConfigBridge, PetSnapshotBridge } from '../shared/types/electron-api';

import { bubbleText, resolveAnimation, resolveInteraction } from './engine/animation';
import { packFor } from './engine/packs';

const EMPTY_SNAPSHOT: PetSnapshotBridge = {
  action: 'idle',
  detail: null,
  sessionId: null,
  sessionTitle: null,
  bubbleKey: null,
  bubbleKind: null,
  activeSessions: 0,
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

export function PetApp(): JSX.Element {
  const [snapshot, setSnapshot] = useState<PetSnapshotBridge>(EMPTY_SNAPSHOT);
  const [config, setConfig] = useState<PetConfigBridge>(DEFAULT_CONFIG);
  const [override, setOverride] = useState<PlaybackOverride | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const dragRef = useRef({ down: false, moved: false, startX: 0, startY: 0 });
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
      if (alive) {
        setSnapshot(value);
        setOverride(null);
      }
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

  const pack = useMemo(() => packFor(config.petPack), [config.petPack]);

  const choice = useMemo(
    () => override ?? resolveAnimation(snapshot, pack),
    [override, snapshot, pack],
  );

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

  const handleClick = useCallback(() => {
    const click = resolveInteraction(pack, 'click');
    if (click) setOverride(click);
    if (snapshot.sessionId) pet?.openSession(snapshot.sessionId);
  }, [pack, pet, snapshot.sessionId]);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return;
    dragRef.current = {
      down: true,
      moved: false,
      startX: event.screenX,
      startY: event.screenY,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    pet?.dragStart();
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>): void => {
    const drag = dragRef.current;
    if (!drag.down) return;
    if (!drag.moved && Math.hypot(event.screenX - drag.startX, event.screenY - drag.startY) > 4) {
      drag.moved = true;
    }
    if (drag.moved) pet?.dragMove();
  };

  const handlePointerUp = (event: React.PointerEvent<HTMLDivElement>): void => {
    const drag = dragRef.current;
    if (!drag.down) return;
    drag.down = false;
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // Pointer may already be released.
    }
    pet?.dragEnd();
    if (!drag.moved) handleClick();
  };

  const handleEnded = (): void => {
    if (override) setOverride(null);
  };

  const bubble = bubbleText(snapshot.bubbleKey);
  const bubbleClass = snapshot.bubbleKind
    ? `pet-bubble pet-bubble-${snapshot.bubbleKind}`
    : 'pet-bubble';

  return (
    <div
      className="pet-root"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onContextMenu={(event) => {
        event.preventDefault();
        pet?.showMenu();
      }}
    >
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
  );
}
