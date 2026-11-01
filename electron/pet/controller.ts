/**
 * Pet controller — owns config, aggregated agent state, and the overlay window.
 *
 * Stream tracking is fed by main.ts (chat stream creation) and by the
 * renderer reattach path. Every event goes through the pure reducer in
 * state.ts; the renderer only receives a small PetSnapshot.
 */

import { Menu, type WebContents } from 'electron';
import { join } from 'node:path';

import { fetchCompat } from '../fetchCompat';
import type { WebContentsLike } from '../relay';
import { relayChatStream } from '../relay';
import { logger } from '../logger';
import { mapOrchestrationLanes, mapScheduledTasks } from './backgroundTasks';
import { mergePetConfig, readPetConfig, writePetConfig } from './config';
import { shouldShowDesktop, shouldShowInApp } from './display';
import {
  deleteUserPack,
  exportPackZip,
  importPackZip,
  listUserPacks,
  petPacksDir,
  type DeleteResult,
  type ExportResult,
} from './packStore';
import {
  bondDays,
  readPetProfile,
  recordPat as incrementPat,
  writePetProfile,
  type PetProfile,
} from './profile';
import {
  applyEvent,
  applyMeta,
  createEmptyState,
  selectSnapshot,
  tick,
  type PetAgentEvent,
  type PetSessionState,
} from './state';
import { PetStatusServer, type StatusServerInfo } from './statusServer';
import { applyTaskOverrides, mergeTaskReports, normalizeTaskReports } from './tasks';
import { PetWindow } from './windows';
import type {
  PetBubbleMode,
  PetConfig,
  PetInstanceConfig,
  PetPackManifest,
  PetRenderConfig,
  PetSessionMeta,
  PetSize,
  PetSnapshot,
  PetTaskReport,
  PetTempo,
} from './types';

export interface PetPackImportResponse {
  ok: boolean;
  canceled?: boolean;
  error?: string;
  manifest?: PetPackManifest;
  config?: PetConfig;
}

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

/** Orchestration/scheduled sources are polled while the pet is visible. */
const BACKGROUND_POLL_MS = 20_000;
const BACKGROUND_FETCH_TIMEOUT_MS = 5_000;

export class PetController {
  private config: PetConfig;
  private sessions: PetSessionState = createEmptyState();
  private snapshot: PetSnapshot;
  private readonly windows = new Map<string, PetWindow>();
  private readonly configFile: string;
  private readonly profileFile: string;
  private readonly packsDir: string;
  private profile: PetProfile;
  private reportedTasks: PetTaskReport[] = [];
  private remoteTasks: PetTaskReport[] = [];
  private statusServer: PetStatusServer | null = null;
  private statusGeneration = 0;
  private statusError: string | null = null;
  private backgroundTimer: ReturnType<typeof setInterval> | null = null;
  private backgroundInFlight = false;
  private readonly streams = new Map<string, AbortController>();
  private readonly titles = new Map<string, string>();
  private tickTimer: ReturnType<typeof setInterval> | null = null;
  private lastSent = '';

  constructor(private readonly options: PetControllerOptions) {
    this.configFile = join(options.userDataDir, 'pet-config.json');
    this.profileFile = join(options.userDataDir, 'pet-profile.json');
    this.packsDir = petPacksDir(options.userDataDir);
    this.config = readPetConfig(this.configFile);
    this.profile = readPetProfile(this.profileFile, Date.now());
    this.snapshot = selectSnapshot(this.sessions, Date.now());
  }

  init(): void {
    writePetProfile(this.profileFile, this.profile);
    this.syncWindows();
    this.broadcastConfig();
    this.tickTimer = setInterval(() => this.onTick(), 500);
    this.backgroundTimer = setInterval(
      () => void this.refreshBackgroundTasks(),
      BACKGROUND_POLL_MS,
    );
    void this.refreshBackgroundTasks();
    if (this.config.externalApi) void this.startStatusServer();
    this.emit(true);
  }

  dispose(): void {
    if (this.tickTimer) {
      clearInterval(this.tickTimer);
      this.tickTimer = null;
    }
    if (this.backgroundTimer) {
      clearInterval(this.backgroundTimer);
      this.backgroundTimer = null;
    }
    for (const abort of this.streams.values()) abort.abort();
    this.streams.clear();
    this.stopStatusServer();
    for (const window of this.windows.values()) window.destroy();
    this.windows.clear();
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

  getApiInfo(): StatusServerInfo {
    const info = this.statusServer?.getInfo() ?? { enabled: false, port: null };
    return { ...info, error: this.statusError };
  }

  setConfig(patch: unknown): PetConfig {
    const previous = this.config;
    const next = mergePetConfig(previous, patch);
    this.config = next;
    if (!writePetConfig(this.configFile, next)) {
      logger.warn('pet: config save failed');
    }
    this.syncWindows();
    this.broadcastConfig();
    this.emit(true);
    if (next.enabled !== previous.enabled || next.displayMode !== previous.displayMode) {
      void this.refreshBackgroundTasks();
    }
    if (next.externalApi !== previous.externalApi) {
      if (next.externalApi) void this.startStatusServer();
      else this.stopStatusServer();
    }
    return next;
  }

  trackStream(streamId: string, sessionId: string | null, contextMax: number | null = null): void {
    if (!streamId || this.streams.has(streamId)) return;
    const abort = new AbortController();
    this.streams.set(streamId, abort);
    const key = sessionId || `stream:${streamId}`;
    if (sessionId) {
      const cachedTitle = this.titles.get(sessionId);
      if (cachedTitle) {
        this.sessions = applyMeta(this.sessions, key, { sessionTitle: cachedTitle }, Date.now());
      }
      if (contextMax !== null && Number.isFinite(contextMax) && contextMax > 0) {
        this.sessions = applyMeta(this.sessions, key, { contextMax }, Date.now());
      }
      void this.fetchSessionTitle(sessionId, key);
    }
    let contextRefreshed = false;
    const refreshContext = (): void => {
      if (!sessionId || contextRefreshed) return;
      contextRefreshed = true;
      void this.refreshContextUsage(sessionId, key, contextMax);
    };
    const sink: WebContentsLike = {
      send: (_channel, payload) => {
        const event = (payload ?? {}) as PetAgentEvent;
        this.sessions = applyEvent(this.sessions, key, event, Date.now());
        this.emit();
        if (event.state === 'done') refreshContext();
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
        refreshContext();
      });
  }

  setPanelOpen(sender: WebContents, open: boolean): void {
    this.windowForSender(sender)?.setPanelOpen(open);
  }

  recordPat(): void {
    this.profile = incrementPat(this.profile, Date.now());
    if (!writePetProfile(this.profileFile, this.profile)) {
      logger.warn('pet: profile save failed');
    }
    this.emit(true);
  }

  reportTasks(input: unknown): void {
    this.reportedTasks = normalizeTaskReports(input);
    this.emit(true);
  }

  /** Installed user packs. Built-in packs are bundled with the renderer. */
  listPacks(): PetPackManifest[] {
    return listUserPacks(this.packsDir).map((pack) => pack.manifest);
  }

  /**
   * Import a pack from a zip and select it. On failure the previous pack
   * stays active; the config is only written after extraction succeeded.
   */
  importPack(zipPath: string): PetPackImportResponse {
    const result = importPackZip(this.packsDir, zipPath);
    if (!result.ok) return { ok: false, error: result.error };
    const config = this.setConfig({ petPack: result.manifest.id });
    return { ok: true, manifest: result.manifest, config };
  }

  exportPack(id: string, destPath: string): ExportResult {
    return exportPackZip(this.packsDir, id, destPath);
  }

  /** Delete a user pack; any pet using it falls back to the built-in pack. */
  deletePack(id: string): DeleteResult {
    const result = deleteUserPack(this.packsDir, id);
    if (result.ok && this.config.pets.some((pet) => pet.petPack === id)) {
      this.setConfig({
        pets: this.config.pets.map((pet) =>
          pet.petPack === id ? { ...pet, petPack: 'dafeiyu' } : pet,
        ),
      });
    }
    return result;
  }

  private async startStatusServer(): Promise<void> {
    if (this.statusServer) return;
    this.statusError = null;
    const server = new PetStatusServer({ userDataDir: this.options.userDataDir });
    server.update(this.snapshot, this.config);
    this.statusServer = server;
    const generation = ++this.statusGeneration;
    try {
      await server.start();
      if (
        generation !== this.statusGeneration ||
        !this.config.externalApi ||
        this.statusServer !== server
      ) {
        server.stop();
        if (this.statusServer === server) this.statusServer = null;
      }
    } catch (error) {
      if (this.statusServer === server) this.statusServer = null;
      if (generation === this.statusGeneration) {
        this.statusError = error instanceof Error ? error.message : String(error);
      }
      logger.warn('pet: status API start failed', {
        err: error instanceof Error ? error.message : String(error),
      });
    }
  }

  private stopStatusServer(): void {
    this.statusGeneration += 1;
    this.statusServer?.stop();
    this.statusServer = null;
    this.statusError = null;
  }

  private authHeaders(): Record<string, string> {
    const token = this.options.getAuthToken();
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  }

  private async fetchJson(path: string): Promise<unknown> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), BACKGROUND_FETCH_TIMEOUT_MS);
    try {
      const res = await fetchCompat(`${this.options.backendUrl}${path}`, {
        method: 'GET',
        headers: this.authHeaders(),
        signal: controller.signal,
      });
      if (!res.ok) return null;
      return (await res.json()) as unknown;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Poll orchestration lanes and scheduled tasks while the pet is visible.
   * Best-effort: a down/slow backend keeps the previous snapshot.
   */
  private async refreshBackgroundTasks(): Promise<void> {
    if (this.backgroundInFlight) return;
    if (!this.config.enabled || this.config.displayMode === 'off') {
      if (this.remoteTasks.length > 0) {
        this.remoteTasks = [];
        this.emit();
      }
      return;
    }
    this.backgroundInFlight = true;
    try {
      const [lanes, scheduled] = await Promise.all([
        this.fetchJson('/api/v1/orchestration/lanes?limit=20'),
        this.fetchJson('/api/v1/scheduled/tasks'),
      ]);
      const now = Date.now();
      this.remoteTasks = mergeTaskReports(
        mapOrchestrationLanes(lanes, now),
        mapScheduledTasks(scheduled, now),
      );
      this.emit();
    } catch {
      // Background sources are optional; keep the last known snapshot.
    } finally {
      this.backgroundInFlight = false;
    }
  }

  private async fetchSessionTitle(sessionId: string, key: string): Promise<void> {
    try {
      const res = await fetchCompat(
        `${this.options.backendUrl}/api/v1/sessions/${encodeURIComponent(sessionId)}`,
        { method: 'GET', headers: this.authHeaders() },
      );
      if (!res.ok) return;
      const data = (await res.json()) as { title?: unknown };
      const title = typeof data.title === 'string' ? data.title.trim() : '';
      if (!title) return;
      this.titles.set(sessionId, title);
      this.sessions = applyMeta(this.sessions, key, { sessionTitle: title }, Date.now());
      this.emit();
    } catch {
      // Best-effort metadata; the panel falls back to the short session id.
    }
  }

  private async refreshContextUsage(
    sessionId: string,
    key: string,
    contextMax: number | null,
  ): Promise<void> {
    try {
      const res = await fetchCompat(
        `${this.options.backendUrl}/api/v1/usage/requests?session_id=${encodeURIComponent(sessionId)}&limit=1`,
        { method: 'GET', headers: this.authHeaders() },
      );
      if (!res.ok) return;
      const data = (await res.json()) as {
        items?: Array<{ prompt_tokens?: unknown }>;
      };
      const used = Number(data.items?.[0]?.prompt_tokens);
      if (!Number.isFinite(used) || used <= 0) return;
      const meta: PetSessionMeta = { contextUsed: used };
      if (contextMax !== null && Number.isFinite(contextMax) && contextMax > 0) {
        meta.contextMax = contextMax;
      }
      this.sessions = applyMeta(this.sessions, key, meta, Date.now());
      this.emit();
    } catch {
      // Usage data is optional; keep the last known values.
    }
  }

  /** Full config for the settings window; per-pet view for a pet window. */
  getConfigForSender(sender: WebContents): PetConfig | PetRenderConfig {
    const pet = this.petForSender(sender);
    return pet ? this.renderConfig(pet) : this.config;
  }

  windowReady(sender: WebContents): void {
    const pet = this.petForSender(sender);
    if (!pet) return;
    this.windows.get(pet.id)?.show();
    this.windows.get(pet.id)?.sendConfig(this.renderConfig(pet));
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
    if (this.windows.size > 0) {
      const anyVisible = [...this.windows.values()].some((window) => window.isVisible());
      for (const window of this.windows.values()) {
        if (anyVisible) window.hide();
        else window.show();
      }
      return;
    }
    if (shouldShowInApp(this.config)) {
      this.setConfig({ enabled: !this.config.enabled });
      return;
    }
    this.setConfig({
      enabled: true,
      ...(this.config.displayMode === 'off' ? { displayMode: 'desktop' } : {}),
    });
  }

  resetPosition(): void {
    for (const window of this.windows.values()) window.resetPosition();
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

  startDrag(sender: WebContents): void {
    this.windowForSender(sender)?.startDrag();
  }

  moveDrag(sender: WebContents): void {
    this.windowForSender(sender)?.moveDrag();
  }

  endDrag(sender: WebContents): void {
    this.windowForSender(sender)?.endDrag();
  }

  hideForNow(sender: WebContents): void {
    this.windowForSender(sender)?.hide();
  }

  showMenu(sender: WebContents): void {
    const pet = this.petForSender(sender);
    if (!pet) return;
    const window = this.windows.get(pet.id);
    if (!window) return;
    const setPetSize = (size: PetSize): void => {
      this.setConfig({
        pets: this.config.pets.map((item) => (item.id === pet.id ? { ...item, size } : item)),
      });
    };
    const sizes = Object.keys(SIZE_LABELS) as PetSize[];
    const tempos = Object.keys(TEMPO_LABELS) as PetTempo[];
    const bubbles = Object.keys(BUBBLE_LABELS) as PetBubbleMode[];
    const menu = Menu.buildFromTemplate([
      {
        label: '大小',
        submenu: sizes.map((size) => ({
          label: SIZE_LABELS[size],
          type: 'radio' as const,
          checked: pet.size === size,
          click: () => setPetSize(size),
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
      { label: '打开会话', click: () => this.openSession(this.snapshot.sessionId) },
      { label: '回到初始位置', click: () => window.resetPosition() },
      { label: '宠物设置…', click: () => this.openSettings() },
      { label: '本次隐藏', click: () => window.hide() },
      { type: 'separator' as const },
      { label: '关闭桌宠', click: () => this.setConfig({ enabled: false }) },
    ]);
    window.popupMenu(menu);
  }

  isPetSender(sender: WebContents): boolean {
    return Boolean(this.petForSender(sender));
  }

  isMainSender(sender: WebContents): boolean {
    const main = this.options.getMainWindow();
    return Boolean(main && !main.isDestroyed() && main.webContents === sender);
  }

  private windowForSender(sender: WebContents): PetWindow | null {
    for (const window of this.windows.values()) {
      if (window.ownsSender(sender)) return window;
    }
    return null;
  }

  private petForSender(sender: WebContents): PetInstanceConfig | null {
    for (const [id, window] of this.windows) {
      if (!window.ownsSender(sender)) continue;
      return this.config.pets.find((pet) => pet.id === id) ?? null;
    }
    return null;
  }

  private onTick(): void {
    this.sessions = tick(this.sessions, Date.now());
    this.emit();
  }

  private syncWindows(): void {
    const desired = shouldShowDesktop(this.config) ? this.config.pets : [];
    const desiredIds = new Set(desired.map((pet) => pet.id));
    for (const [id, window] of [...this.windows]) {
      if (desiredIds.has(id)) continue;
      window.destroy();
      this.windows.delete(id);
    }
    desired.forEach((pet, index) => {
      const render = this.renderConfig(pet);
      const existing = this.windows.get(pet.id);
      if (existing) {
        if (existing.needsRecreate(render)) {
          existing.destroy();
          this.windows.delete(pet.id);
        } else {
          existing.applyConfig(render);
          return;
        }
      }
      const window = new PetWindow({
        config: render,
        petId: pet.id,
        instanceIndex: index,
        devUrl: this.options.devUrl,
        isPackaged: this.options.isPackaged,
        userDataDir: this.options.userDataDir,
      });
      this.windows.set(pet.id, window);
      window.create();
    });
  }

  private renderConfig(pet: PetInstanceConfig): PetRenderConfig {
    return { ...this.config, petId: pet.id, petPack: pet.petPack, size: pet.size };
  }

  private emit(force = false): void {
    const now = Date.now();
    const base = selectSnapshot(this.sessions, now);
    const tasks = mergeTaskReports(this.reportedTasks, this.remoteTasks);
    const withMeta = {
      ...base,
      patCount: this.profile.patCount,
      bondDays: bondDays(this.profile, now),
      tasks,
    };
    const snapshot = this.applyBubbleMode(applyTaskOverrides(withMeta, tasks, now));
    // Ignore updatedAt for dedupe: an idle snapshot's updatedAt changes on
    // every tick and would otherwise push IPC every 500ms forever.
    const key = JSON.stringify({ ...snapshot, updatedAt: 0 });
    if (!force && key === this.lastSent) return;
    this.lastSent = key;
    this.snapshot = snapshot;
    this.statusServer?.update(snapshot, this.config);
    for (const window of this.windows.values()) window.sendState(snapshot);
    if (shouldShowInApp(this.config)) {
      this.sendToMain('pet:state', snapshot);
    }
  }

  private sendToMain(channel: string, payload: unknown): void {
    const main = this.options.getMainWindow();
    if (!main || main.isDestroyed()) return;
    main.webContents.send(channel, payload);
  }

  private broadcastConfig(): void {
    for (const pet of this.config.pets) {
      this.windows.get(pet.id)?.sendConfig(this.renderConfig(pet));
    }
    this.sendToMain('pet:config', this.config);
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
