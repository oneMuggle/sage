import type { GovernanceData } from '../useGovernanceProject';

export interface SettingsSectionProps {
  data: GovernanceData;
  activeTab: string;
  onStartSession: () => void;
}

export function SettingsSection(_props: SettingsSectionProps) {
  return <div data-testid="section-settings">Chapter: settings</div>;
}
