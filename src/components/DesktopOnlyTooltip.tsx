// src/components/DesktopOnlyTooltip.tsx
import { usePlatform } from '../hooks/usePlatform';
import { Tooltip } from '../shared/ui/Tooltip/Tooltip';

interface DesktopOnlyTooltipProps {
  children: React.ReactNode;
  featureName: string;
}

export function DesktopOnlyTooltip({ children, featureName }: DesktopOnlyTooltipProps) {
  const { isElectron } = usePlatform();

  if (isElectron) {
    return <>{children}</>;
  }

  return (
    <Tooltip content={`${featureName} 仅在桌面版可用`}>
      <div style={{ opacity: 0.5, pointerEvents: 'none' }}>{children}</div>
    </Tooltip>
  );
}
