/**
 * Pet controller — owns config, aggregated agent state, and the overlay window.
 *
 * Stream tracking is fed by main.ts (chat stream creation) and by the
 * renderer reattach path. Every event goes through the pure reducer in
 * state.ts; the renderer only receives a small PetSnapshot.
 */

import { Menu, type WebContents } from 'electron';
import { join } from 'node:path';

import type { WebContentsLike } from '../relay';
import { relayChatStream } from '../relay';
import { logger } from '../logger';
import { mergePetConfig, readPetConfig, writePetConfig } from './config';
import {
  applyEvent,
  createEmptyState,
  selectSnapshot,
  tick,
  type PetAgentEvent,
  type PetSessionState,
} from './state';
import { PetWindow } from './windows';
import type { PetBubbleMode, PetConfig, PetSize, PetSnapshot, PetTempo } from './types';

export interface PetControllerOptions {
  backendUrl: string;
  getAuthToken: () => string | null;
  getMainWindow: () => Electron.BrowserWindow | null;
  devUrl: string;
  isPackaged: boolean;
  userDataDir: string;
}

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

export class PetController {
  private config: PetConfig;
  private sessions: PetSessionState = createEmptyState();
  private snapshot: PetSnapshot;
  private window: PetWindow | null = null;
  private readonly configFile: string;
  private readonly streams = new Map<string, AbortController>();
  private tickTimer: ReturnType<typeof setInterval> | null = null;
  private lastSent = '';

  constructor(private readonly options: PetControllerOptions) {
    this.configFile = join(options.userDataDir, 'pet-config.json');
    this.config = readPetConfig(this.configFile);
    this.snapshot = selectSnapshot(this.sessions, Date.now());
  }

  init(): void {
    this.syncWindow();
    this.tickTimer = setInterval(() => this.onTick(), 500);
    this.emit(true);
  }

  dispose(): void {
    if (this.tickTimer) {
      clearInterval(this.tickTimer);
      this.tickTimer = null;
    }
    for (const abort of this.streams.values()) abort.abort();
    this.streams.clear();
    this.window?.destroy();
    this.window = null;
  }

  getConfig(): PetConfig {
    return this.config;
  }

  getState(): PetSnapshot {
    return this.snapshot;
  }

  getMainWindow(): Electron.BrowserWindow | null {
    return this.options.getMainWindow();
  }

  setConfig(patch: unknown): PetConfig {
    const next = mergePetConfig(this.config, patch);
    this.config = next;
    if (!writePetConfig(this.configFile, next)) {
      logger.warn('pet: config save failed');
    }
    this.syncWindow();
    this.window?.sendConfig(next);
    this.emit(true);
    return next;
  }

  trackStream(streamId: string, sessionId: string | null): void {
    if (!streamId || this.streams.has(streamId)) return;
    const abort = new AbortController();
    this.streams.set(streamId, abort);
    const key = sessionId || `stream:${streamId}`;
    const sink: WebContentsLike = {
      send: (_channel, payload) => {
        this.sessions = applyEvent(
          this.sessions,
          key,
          (payload ?? {}) as PetAgentEvent,
          Date.now(),
        );
        this.emit();
      },
    };
    relayChatStream(
      sink,
      'pet',
      streamId,
      this.options.backendUrl,
      abort.signal,
      this.options.getAuthToken() ?? undefined,
    )
      .catch(() => undefined)
      .finally(() => {
        this.streams.delete(streamId);
        const current = this.sessions[key];
        if (current && current.action !== 'done' && current.action !== 'error') {
          this.sessions = applyEvent(this.sessions, key, { state: 'idle' }, Date.now());
          this.emit();
        }
      });
  }

  windowReady(): void {
    this.window?.show();
    this.window?.sendConfig(this.config);
    this.emit(true);
  }

  toggle(): void {
    const enabled = !this.config.enabled;
    this.setConfig({
      enabled,
      ...(enabled && this.config.displayMode === 'off' ? { displayMode: 'desktop' } : {}),
    });
  }

  toggleVisible(): void {
    if (!this.window) {
      this.setConfig({
        enabled: true,
        ...(this.config.displayMode === 'off' ? { displayMode: 'desktop' } : {}),
      });
      return;
    }
    this.window.toggleVisible();
  }

  resetPosition(): void {
    this.window?.resetPosition();
  }

  openSession(sessionId: string | null): void {
    const main = this.options.getMainWindow();
    if (!main || main.isDestroyed()) return;
    if (main.isMinimized()) main.restore();
    main.show();
    main.focus();
    if (sessionId) {
      main.webContents.send('sage:event:session-notify-click', { sessionId });
    }
  }

  openSettings(): void {
    const main = this.options.getMainWindow();
    if (!main || main.isDestroyed()) return;
    if (main.isMinimized()) main.restore();
    main.show();
    main.focus();
    main.webContents.send('sage:event:open-settings', { tab: 'pet' });
  }

  startDrag(): void {
    this.window?.startDrag();
  }

  moveDrag(): void {
    this.window?.moveDrag();
  }

  endDrag(): void {
    this.window?.endDrag();
  }

  hideForNow(): void {
    this.window?.hide();
  }

  showMenu(): void {
    if (!this.window) return;
    const sizes = Object.keys(SIZE_LABELS) as PetSize[];
    const tempos = Object.keys(TEMPO_LABELS) as PetTempo[];
    const bubbles = Object.keys(BUBBLE_LABELS) as PetBubbleMode[];
    const menu = Menu.buildFromTemplate([
      {
        label: '大小',
        submenu: sizes.map((size) => ({
          label: SIZE_LABELS[size],
          type: 'radio' as const,
          checked: this.config.size === size,
          click: () => this.setConfig({ size }),
        })),
      },
      {
        label: '节奏',
        submenu: tempos.map((tempo) => ({
          label: TEMPO_LABELS[tempo],
          type: 'radio' as const,
          checked: this.config.tempo === tempo,
          click: () => this.setConfig({ tempo }),
        })),
      },
      {
        label: '减少动态',
        type: 'checkbox' as const,
        checked: this.config.reduceMotion,
        click: () => this.setConfig({ reduceMotion: !this.config.reduceMotion }),
      },
      {
        label: '气泡',
        submenu: bubbles.map((bubbleMode) => ({
          label: BUBBLE_LABELS[bubbleMode],
          type: 'radio' as const,
          checked: this.config.bubbleMode === bubbleMode,
          click: () => this.setConfig({ bubbleMode }),
        })),
      },
      { type: 'separator' as const },
      { label: '回到初始位置', click: () => this.resetPosition() },
      { label: '宠物设置…', click: () => this.openSettings() },
      { label: '本次隐藏', click: () => this.hideForNow() },
      { type: 'separator' as const },
      { label: '关闭桌宠', click: () => this.setConfig({ enabled: false }) },
    ]);
    this.window.popupMenu(menu);
  }

  isPetSender(sender: WebContents): boolean {
    return this.window?.ownsSender(sender) ?? false;
  }

  isMainSender(sender: WebContents): boolean {
    const main = this.options.getMainWindow();
    return Boolean(main && !main.isDestroyed() && main.webContents === sender);
  }

  private onTick(): void {
    this.sessions = tick(this.sessions, Date.now());
    this.emit();
  }

  private syncWindow(): void {
    if (this.window && this.window.needsRecreate(this.config)) {
      this.window.destroy();
      this.window = null;
    }
    if (!PetWindow.shouldShow(this.config)) {
      this.window?.destroy();
      this.window = null;
      return;
    }
    if (!this.window) {
      this.window = new PetWindow({
        config: this.config,
        devUrl: this.options.devUrl,
        isPackaged: this.options.isPackaged,
        userDataDir: this.options.userDataDir,
      });
      this.window.create();
      return;
    }
    this.window.applyConfig(this.config);
  }

  private emit(force = false): void {
    const base = selectSnapshot(this.sessions, Date.now());
    const snapshot = this.applyBubbleMode(base);
    // Ignore updatedAt for dedupe: an idle snapshot's updatedAt changes on
    // every tick and would otherwise push IPC every 500ms forever.
    const key = JSON.stringify({ ...snapshot, updatedAt: 0 });
    if (!force && key === this.lastSent) return;
    this.lastSent = key;
    this.snapshot = snapshot;
    this.window?.sendState(snapshot);
  }

  private applyBubbleMode(snapshot: PetSnapshot): PetSnapshot {
    if (this.config.bubbleMode === 'off') {
      return { ...snapshot, bubbleKey: null, bubbleKind: null };
    }
    if (
      this.config.bubbleMode === 'important' &&
      snapshot.action !== 'waiting' &&
      snapshot.action !== 'error' &&
      snapshot.action !== 'done'
    ) {
      return { ...snapshot, bubbleKey: null, bubbleKind: null };
    }
    return snapshot;
  }
}
