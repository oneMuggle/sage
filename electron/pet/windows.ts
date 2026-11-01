/**
 * Pet overlay window lifecycle.
 *
 * Ideas adapted from dsh-pet's electron-helper (MIT): whole-window
 * click-through mirroring, a 60ms cursor fallback, drag, topmost watchdog,
 * multi-display clamping. Rewritten for Sage's single-window P0.
 */

import { BrowserWindow, Menu, screen, type WebContents } from 'electron';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { logger } from '../logger';
import { shouldShowDesktop } from './display';
import {
  clampToWorkArea,
  defaultPosition,
  isPointInRect,
  petHitBox,
  petWindowSize,
  type Point,
} from './geometry';
import type { PetConfig, PetRenderConfig, PetSnapshot } from './types';

interface StoredPosition {
  x: number;
  y: number;
}

export interface PetWindowOptions {
  config: PetRenderConfig;
  petId: string;
  instanceIndex: number;
  devUrl: string;
  isPackaged: boolean;
  userDataDir: string;
}

const POINTER_POLL_MS = 60;
const TOPMOST_WATCHDOG_MS = 5_000;
const SHOW_FALLBACK_MS = 3_000;

/** Separate status panel window: anchored above the pet, never resizes it. */
const PANEL_WINDOW_HEIGHT = 360;
const PANEL_MIN_WIDTH = 320;
const PANEL_MAX_WIDTH = 480;
const PANEL_GAP = 8;

function isLegacyWindows(): boolean {
  if (process.platform !== 'win32') return false;
  try {
    const major = Number(process.getSystemVersion().split('.')[0]);
    return Number.isFinite(major) && major < 10;
  } catch {
    return false;
  }
}

function compatibilityEnabled(config: PetConfig): boolean {
  if (config.compatibilityMode === 'on') return true;
  if (config.compatibilityMode === 'off') return false;
  return isLegacyWindows();
}

function readStoredPosition(file: string): StoredPosition | null {
  try {
    if (!existsSync(file)) return null;
    const parsed = JSON.parse(readFileSync(file, 'utf8')) as Partial<StoredPosition>;
    if (typeof parsed.x !== 'number' || typeof parsed.y !== 'number') return null;
    if (!Number.isFinite(parsed.x) || !Number.isFinite(parsed.y)) return null;
    return { x: parsed.x, y: parsed.y };
  } catch {
    return null;
  }
}

export class PetWindow {
  private win: BrowserWindow | null = null;
  private config: PetRenderConfig;
  private readonly positionFile: string;
  private pointerTimer: ReturnType<typeof setInterval> | null = null;
  private topmostTimer: ReturnType<typeof setInterval> | null = null;
  private showFallback: ReturnType<typeof setTimeout> | null = null;
  private ignoring = false;
  private pointerFallbackBroken = false;
  private dragging = false;
  private dragStartCursor: Point | null = null;
  private dragStartPosition: Point | null = null;
  private compatibility: boolean;
  private panel: BrowserWindow | null = null;
  private panelVisible = false;

  constructor(private readonly options: PetWindowOptions) {
    this.config = options.config;
    this.compatibility = compatibilityEnabled(options.config);
    // Keep the legacy filename for the first/default pet so existing user
    // positions survive the v2 migration.
    this.positionFile = join(
      options.userDataDir,
      options.petId === 'default' ? 'pet-window.json' : `pet-window-${options.petId}.json`,
    );
  }

  static shouldShow(config: PetRenderConfig | PetConfig): boolean {
    return shouldShowDesktop(config);
  }

  needsRecreate(config: PetRenderConfig): boolean {
    return compatibilityEnabled(config) !== this.compatibility;
  }

  create(): void {
    if (this.win && !this.win.isDestroyed()) return;
    const size = petWindowSize(this.config.size);
    const cursor = screen.getCursorScreenPoint();
    const display = screen.getDisplayNearestPoint(cursor);
    const stored = readStoredPosition(this.positionFile);
    const base = stored ?? defaultPosition(display.workArea, size);
    // Stack additional pets to the left of the default bottom-right corner so
    // they don't spawn on top of each other; stored positions are respected.
    const offset = stored ? 0 : this.options.instanceIndex * (size.width + 12);
    const position = clampToWorkArea({ x: base.x - offset, y: base.y }, size, display.workArea);

    const transparent = !this.compatibility;
    const preload = join(__dirname, '..', 'preload.js');
    this.win = new BrowserWindow({
      x: position.x,
      y: position.y,
      width: size.width,
      height: size.height,
      show: false,
      transparent,
      backgroundColor: transparent ? '#00000000' : '#111827',
      frame: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      resizable: false,
      movable: true,
      hasShadow: false,
      focusable: false,
      acceptFirstMouse: true,
      webPreferences: {
        preload,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: !(isLegacyWindows() || process.env.SAGE_NO_SANDBOX === '1'),
        // The shared preload exposes only the narrow `pet` bridge when this
        // marker is present. Keep the pet window out of every other bridge.
        additionalArguments: ['--sage-pet-window=1'],
      },
    });

    this.win.setAlwaysOnTop(true, 'floating');
    this.win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    this.win.webContents.on('will-navigate', (event) => event.preventDefault());
    this.win.on('closed', () => {
      this.stopTimers();
      this.win = null;
    });

    if (this.options.isPackaged) {
      const page = join(__dirname, '..', '..', '..', 'dist', 'pet.html');
      this.win.loadFile(page).catch((err: unknown) => {
        logger.error('pet: loadFile failed', {
          page,
          err: err instanceof Error ? err.message : String(err),
        });
      });
    } else {
      const page = `${this.options.devUrl}/pet.html`;
      this.win.loadURL(page).catch((err: unknown) => {
        logger.error('pet: loadURL failed', {
          page,
          err: err instanceof Error ? err.message : String(err),
        });
      });
    }

    this.win.once('ready-to-show', () => this.show());
    this.showFallback = setTimeout(() => this.show(), SHOW_FALLBACK_MS);
    if (this.clickThroughActive()) this.setIgnoreMouse(true);
    this.startTimers();
  }

  applyConfig(config: PetRenderConfig): void {
    this.config = config;
    this.compatibility = compatibilityEnabled(config);
    if (!this.win || this.win.isDestroyed()) return;
    if (!shouldShowDesktop(config)) {
      this.destroy();
      return;
    }
    const size = petWindowSize(config.size);
    const bounds = this.win.getBounds();
    if (bounds.width !== size.width || bounds.height !== size.height) {
      // Settings-driven size change: keep the bottom edge fixed.
      const display = screen.getDisplayNearestPoint({ x: bounds.x, y: bounds.y });
      const position = clampToWorkArea(
        { x: bounds.x, y: bounds.y + bounds.height - size.height },
        size,
        display.workArea,
      );
      this.win.setBounds(
        { x: position.x, y: position.y, width: size.width, height: size.height },
        false,
      );
    }
    this.syncPanelPosition();
    this.sendConfig(config);
  }

  setPanelOpen(open: boolean): void {
    if (!this.win || this.win.isDestroyed()) return;
    if (open) this.showPanel();
    else this.hidePanel();
  }

  /**
   * The panel is its own window. Resizing the pet window to reveal a panel
   * moved the (bottom-anchored) sprite before the new frame was painted on
   * XWayland — visible as the pet jumping up and back down. A separate
   * window keeps the overlay completely still.
   */
  showPanel(): void {
    if (!this.win || this.win.isDestroyed()) return;
    const panel = this.ensurePanel();
    if (!panel) return;
    this.panelVisible = true;
    panel.setBounds(this.panelBounds(), false);
    panel.showInactive();
  }

  hidePanel(): void {
    this.panelVisible = false;
    if (this.panel && !this.panel.isDestroyed() && this.panel.isVisible()) {
      this.panel.hide();
    }
  }

  togglePanel(): void {
    if (this.isPanelVisible()) this.hidePanel();
    else this.showPanel();
  }

  isPanelVisible(): boolean {
    return Boolean(
      this.panelVisible && this.panel && !this.panel.isDestroyed() && this.panel.isVisible(),
    );
  }

  panelOwnsSender(sender: WebContents): boolean {
    if (!this.panel || this.panel.isDestroyed()) return false;
    return BrowserWindow.fromWebContents(sender) === this.panel;
  }

  sendPanelState(snapshot: PetSnapshot): void {
    this.sendToPanel('pet:state', snapshot);
  }

  sendPanelConfig(config: PetRenderConfig): void {
    this.sendToPanel('pet:config', config);
  }

  private sendToPanel(channel: string, payload: unknown): void {
    if (!this.panel || this.panel.isDestroyed()) return;
    try {
      this.panel.webContents.send(channel, payload);
    } catch {
      // Renderer may be mid-reload; the next push recovers.
    }
  }

  /** Centered above the pet, falling back below it, clamped to the work area. */
  private panelBounds(): { x: number; y: number; width: number; height: number } {
    const pet = this.win!.getBounds();
    const width = Math.min(Math.max(pet.width, PANEL_MIN_WIDTH), PANEL_MAX_WIDTH);
    const height = PANEL_WINDOW_HEIGHT;
    const display = screen.getDisplayNearestPoint({ x: pet.x, y: pet.y });
    let y = pet.y - height - PANEL_GAP;
    if (y < display.workArea.y) y = pet.y + pet.height + PANEL_GAP;
    const position = clampToWorkArea(
      { x: pet.x + Math.round((pet.width - width) / 2), y },
      { width, height },
      display.workArea,
    );
    return { x: position.x, y: position.y, width, height };
  }

  private syncPanelPosition(): void {
    if (!this.panel || this.panel.isDestroyed() || !this.panel.isVisible()) return;
    this.panel.setBounds(this.panelBounds(), false);
  }

  private ensurePanel(): BrowserWindow | null {
    if (this.panel && !this.panel.isDestroyed()) return this.panel;
    const preload = join(__dirname, '..', 'preload.js');
    try {
      const panel = new BrowserWindow({
        ...this.panelBounds(),
        show: false,
        frame: false,
        resizable: false,
        movable: false,
        hasShadow: true,
        alwaysOnTop: true,
        skipTaskbar: true,
        focusable: true,
        backgroundColor: '#0f172a',
        webPreferences: {
          preload,
          contextIsolation: true,
          nodeIntegration: false,
          sandbox: !(isLegacyWindows() || process.env.SAGE_NO_SANDBOX === '1'),
          additionalArguments: ['--sage-pet-window=1'],
        },
      });
      panel.setAlwaysOnTop(true, 'floating');
      panel.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
      panel.webContents.on('will-navigate', (event) => event.preventDefault());
      panel.on('closed', () => {
        this.panel = null;
        this.panelVisible = false;
      });
      if (this.options.isPackaged) {
        const page = join(__dirname, '..', '..', '..', 'dist', 'pet.html');
        panel.loadFile(page, { query: { panel: '1' } }).catch((err: unknown) => {
          logger.error('pet: panel loadFile failed', {
            page,
            err: err instanceof Error ? err.message : String(err),
          });
        });
      } else {
        const page = `${this.options.devUrl}/pet.html?panel=1`;
        panel.loadURL(page).catch((err: unknown) => {
          logger.error('pet: panel loadURL failed', {
            page,
            err: err instanceof Error ? err.message : String(err),
          });
        });
      }
      this.panel = panel;
      return panel;
    } catch (err) {
      logger.error('pet: panel window creation failed', {
        err: err instanceof Error ? err.message : String(err),
      });
      return null;
    }
  }

  sendState(snapshot: PetSnapshot): void {
    this.send('pet:state', snapshot);
  }

  sendConfig(config: PetRenderConfig): void {
    this.send('pet:config', config);
  }

  show(): void {
    if (!this.win || this.win.isDestroyed()) return;
    if (this.showFallback) {
      clearTimeout(this.showFallback);
      this.showFallback = null;
    }
    try {
      this.win.setAlwaysOnTop(true, 'floating');
      this.win.showInactive();
    } catch (err) {
      logger.warn('pet: show failed', {
        err: err instanceof Error ? err.message : String(err),
      });
    }
  }

  hide(): void {
    if (!this.win || this.win.isDestroyed()) return;
    this.win.hide();
    this.hidePanel();
    if (this.clickThroughActive()) this.setIgnoreMouse(true);
  }

  toggleVisible(): void {
    if (!this.win || this.win.isDestroyed()) return;
    if (this.win.isVisible()) this.hide();
    else this.show();
  }

  isVisible(): boolean {
    return Boolean(this.win && !this.win.isDestroyed() && this.win.isVisible());
  }

  ownsSender(sender: WebContents): boolean {
    if (!this.win || this.win.isDestroyed()) return false;
    return BrowserWindow.fromWebContents(sender) === this.win;
  }

  popupMenu(menu: Menu): void {
    if (!this.win || this.win.isDestroyed()) return;
    menu.popup({ window: this.win });
  }

  startDrag(): void {
    if (!this.win || this.win.isDestroyed()) return;
    this.dragging = true;
    this.dragStartCursor = screen.getCursorScreenPoint();
    const bounds = this.win.getBounds();
    this.dragStartPosition = { x: bounds.x, y: bounds.y };
    this.setIgnoreMouse(false);
  }

  moveDrag(): void {
    if (!this.dragging || !this.win || this.win.isDestroyed()) return;
    if (!this.dragStartCursor || !this.dragStartPosition) return;
    const cursor = screen.getCursorScreenPoint();
    const size = this.win.getBounds();
    const display = screen.getDisplayNearestPoint(cursor);
    const position = clampToWorkArea(
      {
        x: this.dragStartPosition.x + (cursor.x - this.dragStartCursor.x),
        y: this.dragStartPosition.y + (cursor.y - this.dragStartCursor.y),
      },
      { width: size.width, height: size.height },
      display.workArea,
    );
    this.win.setPosition(position.x, position.y, false);
    this.syncPanelPosition();
  }

  endDrag(): void {
    if (!this.dragging) return;
    this.dragging = false;
    this.dragStartCursor = null;
    this.dragStartPosition = null;
    this.savePosition();
    this.syncPanelPosition();
    if (this.clickThroughActive()) this.setIgnoreMouse(true);
  }

  resetPosition(): void {
    if (!this.win || this.win.isDestroyed()) return;
    const size = petWindowSize(this.config.size);
    const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
    const position = defaultPosition(display.workArea, size);
    this.win.setPosition(position.x, position.y, false);
    this.savePosition();
    this.syncPanelPosition();
  }

  destroy(): void {
    this.stopTimers();
    this.panelVisible = false;
    if (this.panel && !this.panel.isDestroyed()) {
      this.panel.destroy();
    }
    this.panel = null;
    if (this.win && !this.win.isDestroyed()) {
      this.win.destroy();
    }
    this.win = null;
  }

  private send(channel: string, payload: unknown): void {
    if (!this.win || this.win.isDestroyed()) return;
    try {
      this.win.webContents.send(channel, payload);
    } catch {
      // Renderer may be mid-reload; the next state push will recover.
    }
  }

  private savePosition(): void {
    if (!this.win || this.win.isDestroyed()) return;
    const bounds = this.win.getBounds();
    try {
      writeFileSync(
        this.positionFile,
        `${JSON.stringify({ x: bounds.x, y: bounds.y }, null, 2)}\n`,
        'utf8',
      );
    } catch (err) {
      logger.warn('pet: save position failed', {
        err: err instanceof Error ? err.message : String(err),
      });
    }
  }

  private startTimers(): void {
    this.stopTimers();
    this.pointerTimer = setInterval(() => this.pollPointer(), POINTER_POLL_MS);
    this.topmostTimer = setInterval(() => this.reassertTopmost(), TOPMOST_WATCHDOG_MS);
  }

  private stopTimers(): void {
    if (this.pointerTimer) {
      clearInterval(this.pointerTimer);
      this.pointerTimer = null;
    }
    if (this.topmostTimer) {
      clearInterval(this.topmostTimer);
      this.topmostTimer = null;
    }
    if (this.showFallback) {
      clearTimeout(this.showFallback);
      this.showFallback = null;
    }
  }

  private reassertTopmost(): void {
    if (!this.win || this.win.isDestroyed() || !this.win.isVisible()) return;
    try {
      this.win.setAlwaysOnTop(true, 'floating');
    } catch {
      // Some window managers reject the level; the initial flag still applies.
    }
  }

  private pollPointer(): void {
    if (this.compatibility || this.dragging || this.pointerFallbackBroken) return;
    if (!this.win || this.win.isDestroyed() || !this.win.isVisible()) return;
    try {
      const cursor = screen.getCursorScreenPoint();
      const bounds = this.win.getBounds();
      const inside = isPointInRect(cursor, petHitBox(bounds));
      this.setIgnoreMouse(!inside);
    } catch (err) {
      // Wayland / headless sessions may not expose a global cursor. Keep the
      // window fully interactive rather than leaving it permanently click-through.
      this.pointerFallbackBroken = true;
      this.setIgnoreMouse(false);
      logger.warn('pet: cursor polling unavailable; keeping window interactive', {
        err: err instanceof Error ? err.message : String(err),
      });
    }
  }

  /**
   * Click-through is only switched on for the transparent overlay. The opaque
   * compatibility window and the polling-unavailable fallback stay fully
   * interactive — otherwise restoring "click-through" after a drag (or a
   * hide/show cycle) would leave no code path to make the window clickable
   * again.
   */
  private clickThroughActive(): boolean {
    return !this.compatibility && !this.pointerFallbackBroken;
  }

  private setIgnoreMouse(ignore: boolean): void {
    if (!this.win || this.win.isDestroyed()) return;
    if (this.ignoring === ignore) return;
    try {
      if (ignore) {
        this.win.setIgnoreMouseEvents(true, { forward: true });
      } else {
        this.win.setIgnoreMouseEvents(false);
      }
      this.ignoring = ignore;
    } catch (err) {
      // Known Win7/VM failure mode: clicking through can hang the window.
      // Disable the optimization permanently for this window.
      this.pointerFallbackBroken = true;
      this.ignoring = false;
      logger.warn('pet: click-through unavailable; keeping window interactive', {
        err: err instanceof Error ? err.message : String(err),
      });
    }
  }
}
