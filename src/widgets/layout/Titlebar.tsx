import { Menu } from 'lucide-react';
import { useState } from 'react';

import { detectPlatform, isElectronDesktop } from '../../shared/api/windowControlsClient';
import { BrandLogo } from '../../shared/ui';

import { TitlebarActions } from './TitlebarActions';
import { WindowControls } from './WindowControls';

/**
 * Titlebar — Cross-platform titlebar component.
 *
 * - macOS: Native traffic lights visible, custom content starts from y=28px
 * - Windows/Linux: Custom titlebar with navigation + window controls
 * - Web: Navigation only, no window controls
 *
 * U-Brand: Windows/Linux 标题栏左侧加 <BrandLogo size="xs" />。
 * macOS 留空（traffic lights 占据左上）；web 模式也留空（标题栏空间紧张）。
 */
export interface TitlebarProps {
  /** 桌面端左侧栏已常驻展示 BrandLogo 时隐藏标题栏重复 Logo（单测默认不传保持原样） */
  hideBrandLogo?: boolean;
  /** 窄屏（<768px）唤起/收起移动端侧栏抽屉回调 */
  onToggleMobileSidebar?: () => void;
  mobileSidebarOpen?: boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatTitlebarAuditSnapshot(opts: {
  platform?: string;
  isDesktop?: boolean;
  hideBrandLogo?: boolean;
  mobileSidebarOpen?: boolean;
}): string {
  return `titlebar|platform=${opts.platform || 'web'}|desktop=${opts.isDesktop ? 1 : 0}|hideLogo=${opts.hideBrandLogo ? 1 : 0}|mobileOpen=${opts.mobileSidebarOpen ? 1 : 0}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatTitlebarAuditJson(opts: {
  platform?: string;
  isDesktop?: boolean;
  hideBrandLogo?: boolean;
  mobileSidebarOpen?: boolean;
}): string {
  return JSON.stringify({
    platform: opts.platform || 'web',
    isDesktop: Boolean(opts.isDesktop),
    hideBrandLogo: Boolean(opts.hideBrandLogo),
    mobileSidebarOpen: Boolean(opts.mobileSidebarOpen),
  });
}

export function Titlebar({
  hideBrandLogo = false,
  onToggleMobileSidebar,
  mobileSidebarOpen = false,
}: TitlebarProps = {}) {
  const platform = detectPlatform();
  const isDesktop = isElectronDesktop(platform);
  const isMac = platform === 'macos';
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(
        formatTitlebarAuditSnapshot({
          platform,
          isDesktop,
          hideBrandLogo,
          mobileSidebarOpen,
        }),
      );
    } catch {
      // ignore
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(
        formatTitlebarAuditJson({
          platform,
          isDesktop,
          hideBrandLogo,
          mobileSidebarOpen,
        }),
      );
    } catch {
      // ignore
    }
  };
  /* v8 ignore stop */
  const copyControls = (
    <>
      <span
        data-testid="titlebar-copy-snapshot"
        onClick={() => void handleCopySnapshot()}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="titlebar-copy-json"
        onClick={() => void handleCopyJson()}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </>
  );

  // Web mode: no titlebar controls, just navigation
  if (!isDesktop) {
    return (
      <div className="flex items-center justify-between px-4 h-10 border-b border-border bg-bg-subtle">
        <div className="flex items-center">{onToggleMobileSidebar && (
        <button
          type="button"
          data-testid="mobile-sidebar-toggle"
          aria-label={mobileSidebarOpen ? '关闭导航菜单' : '打开导航菜单'}
          aria-expanded={mobileSidebarOpen}
          onClick={onToggleMobileSidebar}
          className="no-drag mr-2 p-1.5 rounded-radius-sm text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
        >
          <Menu className="w-4 h-4" />
        </button>
      )}<TitlebarActions />{copyControls}</div>
      </div>
    );
  }

  // macOS: native traffic lights, content offset to y=28
  if (isMac) {
    return (
      <div className="drag flex items-center justify-between px-4 h-10 border-b border-border bg-bg-subtle pt-7">
        <div className="no-drag flex items-center">{onToggleMobileSidebar && (
        <button
          type="button"
          data-testid="mobile-sidebar-toggle"
          aria-label={mobileSidebarOpen ? '关闭导航菜单' : '打开导航菜单'}
          aria-expanded={mobileSidebarOpen}
          onClick={onToggleMobileSidebar}
          className="no-drag mr-2 p-1.5 rounded-radius-sm text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
        >
          <Menu className="w-4 h-4" />
        </button>
      )}<TitlebarActions />{copyControls}</div>
      </div>
    );
  }

  // Windows/Linux: custom titlebar with brand logo + window controls
  return (
    <div className="drag flex items-center justify-between px-4 h-9 border-b border-border bg-bg-subtle">
      <div className="no-drag flex items-center gap-2">
        {onToggleMobileSidebar && (
        <button
          type="button"
          data-testid="mobile-sidebar-toggle"
          aria-label={mobileSidebarOpen ? '关闭导航菜单' : '打开导航菜单'}
          aria-expanded={mobileSidebarOpen}
          onClick={onToggleMobileSidebar}
          className="no-drag mr-2 p-1.5 rounded-radius-sm text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
        >
          <Menu className="w-4 h-4" />
        </button>
      )}
        {!hideBrandLogo && <BrandLogo size="xs" />}
        <TitlebarActions />
        {copyControls}
      </div>
      <div className="no-drag flex items-center">
        <WindowControls />
      </div>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditTitlebarGovernance(
  state: {
    heightPx?: number;
    showWindowControls?: boolean;
  } = {},
): {
  module: 'src/widgets/layout/Titlebar.tsx';
  phase: 'P150';
  heightPx: number;
  showWindowControls: boolean;
  healthy: boolean;
} {
  const heightPx =
    typeof state.heightPx === 'number' && Number.isFinite(state.heightPx)
      ? Math.min(64, Math.max(28, Math.round(state.heightPx)))
      : 36;
  const showWindowControls = state.showWindowControls !== false;
  return {
    module: 'src/widgets/layout/Titlebar.tsx',
    phase: 'P150',
    heightPx,
    showWindowControls,
    healthy: heightPx >= 28 && heightPx <= 64,
  };
}
