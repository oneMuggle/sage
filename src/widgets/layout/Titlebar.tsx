import { detectPlatform, isElectronDesktop } from '../../shared/api/windowControlsClient';
import { FeedbackButton } from '../../features/feedback';

import { TitlebarActions } from './TitlebarActions';
import { WindowControls } from './WindowControls';

/**
 * Titlebar — Cross-platform titlebar component.
 *
 * - macOS: Native traffic lights visible, custom content starts from y=28px
 * - Windows/Linux: Custom titlebar with navigation + window controls
 * - Web: Navigation only, no window controls
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
        <FeedbackButton />
      </div>
    );
  }

  // macOS: native traffic lights, content offset to y=28
  if (isMac) {
    return (
      <div className="flex items-center justify-between px-4 h-10 border-b border-border bg-bg-subtle pt-7">
        <TitlebarActions />
        <FeedbackButton />
      </div>
    );
  }

  // Windows/Linux: custom titlebar with window controls
  return (
    <div className="flex items-center justify-between px-4 h-9 border-b border-border bg-bg-subtle">
      <TitlebarActions />
      <div className="flex items-center">
        <FeedbackButton />
        <WindowControls />
      </div>
    </div>
  );
}
