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
export function Titlebar() {
  const platform = detectPlatform();
  const isDesktop = isElectronDesktop(platform);
  const isMac = platform === 'macos';

  // Web mode: no titlebar controls, just navigation
  if (!isDesktop) {
    return (
      <div className="flex items-center justify-between px-4 h-10 border-b border-border bg-bg-subtle">
        <TitlebarActions />
      </div>
    );
  }

  // macOS: native traffic lights, content offset to y=28
  if (isMac) {
    return (
      <div className="drag flex items-center justify-between px-4 h-10 border-b border-border bg-bg-subtle pt-7">
        <TitlebarActions />
      </div>
    );
  }

  // Windows/Linux: custom titlebar with brand logo + window controls
  return (
    <div className="drag flex items-center justify-between px-4 h-9 border-b border-border bg-bg-subtle">
      <div className="no-drag flex items-center gap-2">
        <BrandLogo size="xs" />
        <TitlebarActions />
      </div>
      <div className="no-drag flex items-center">
        <WindowControls />
      </div>
    </div>
  );
}
