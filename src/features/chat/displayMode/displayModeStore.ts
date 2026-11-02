import { isValidDisplayMode, type DisplayMode } from './types';

const SESSION_PREFIX = 'sage:display-mode:session:';
const MESSAGE_PREFIX = 'sage:display-mode:message:';

const memory = new Map<string, DisplayMode>();

function readStorage(key: string): DisplayMode | null {
  const cached = memory.get(key);
  if (cached !== undefined) return cached;
  try {
    const raw = sessionStorage.getItem(key);
    if (raw && isValidDisplayMode(raw)) {
      memory.set(key, raw);
      return raw;
    }
  } catch {
    /* sessionStorage unavailable */
  }
  return null;
}

function writeStorage(key: string, value: DisplayMode): void {
  memory.set(key, value);
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* sessionStorage unavailable */
  }
}

function deleteStorage(key: string): void {
  memory.delete(key);
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* sessionStorage unavailable */
  }
}

type DisplayModeListener = () => void;
const listeners = new Set<DisplayModeListener>();
let version = 0;

function emit(): void {
  version += 1;
  for (const listener of listeners) listener();
}

export function subscribeDisplayModeStore(listener: DisplayModeListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getDisplayModeStoreVersion(): number {
  return version;
}

export const displayModeStore = {
  getSession(sessionId: string): DisplayMode | null {
    return readStorage(SESSION_PREFIX + sessionId);
  },

  setSession(sessionId: string, mode: DisplayMode): void {
    writeStorage(SESSION_PREFIX + sessionId, mode);
    emit();
  },

  clearSession(sessionId: string): void {
    deleteStorage(SESSION_PREFIX + sessionId);
    emit();
  },

  getMessage(messageId: string): DisplayMode | null {
    return readStorage(MESSAGE_PREFIX + messageId);
  },

  setMessage(messageId: string, mode: DisplayMode): void {
    writeStorage(MESSAGE_PREFIX + messageId, mode);
    emit();
  },

  clearMessage(messageId: string): void {
    deleteStorage(MESSAGE_PREFIX + messageId);
    emit();
  },

  clearAll(): void {
    memory.clear();
    try {
      const keysToRemove: string[] = [];
      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i);
        if (key && (key.startsWith(SESSION_PREFIX) || key.startsWith(MESSAGE_PREFIX))) {
          keysToRemove.push(key);
        }
      }
      keysToRemove.forEach((k) => sessionStorage.removeItem(k));
    } catch {
      /* sessionStorage unavailable */
    }
    emit();
  },
};
