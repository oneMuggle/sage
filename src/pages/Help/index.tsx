import { useState } from 'react';

import { HelpFooter } from '../../widgets/help/HelpFooter';

import { AboutTab } from './AboutTab';
import { ChangelogTab } from './ChangelogTab';
import { HelpTab } from './HelpTab';


type TabKey = 'help' | 'about' | 'changelog';

interface Tab {
  key: TabKey;
  label: string;
  icon: string;
}

const TABS: Tab[] = [
  { key: 'help', label: '帮助', icon: '📚' },
  { key: 'about', label: '关于', icon: 'ℹ️' },
  { key: 'changelog', label: '更新日志', icon: '📜' },
];

export function Help() {
  const [activeTab, setActiveTab] = useState<TabKey>('help');

  return (
    <div className="flex flex-col h-full bg-bg" data-testid="help-page">
      {/* Tab Navigation */}
      <div className="border-b border-border bg-surface">
        <nav className="flex" role="tablist" aria-label="帮助标签页">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              role="tab"
              aria-selected={activeTab === tab.key}
              aria-controls={`panel-${tab.key}`}
              id={`tab-${tab.key}`}
              onClick={() => setActiveTab(tab.key)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowRight') {
                  const currentIndex = TABS.findIndex((t) => t.key === activeTab);
                  const nextIndex = (currentIndex + 1) % TABS.length;
                  setActiveTab(TABS[nextIndex].key);
                } else if (e.key === 'ArrowLeft') {
                  const currentIndex = TABS.findIndex((t) => t.key === activeTab);
                  const prevIndex = (currentIndex - 1 + TABS.length) % TABS.length;
                  setActiveTab(TABS[prevIndex].key);
                }
              }}
              className={`flex items-center gap-2 px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-primary text-primary'
                  : 'border-transparent text-text-secondary hover:text-text hover:bg-bg-hover'
              }`}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'help' && (
          <div
            role="tabpanel"
            id="panel-help"
            aria-labelledby="tab-help"
            className="h-full"
            data-testid="help-tab"
          >
            <HelpTab />
          </div>
        )}
        {activeTab === 'about' && (
          <div
            role="tabpanel"
            id="panel-about"
            aria-labelledby="tab-about"
            className="h-full overflow-y-auto"
            data-testid="about-tab"
          >
            <AboutTab />
          </div>
        )}
        {activeTab === 'changelog' && (
          <div
            role="tabpanel"
            id="panel-changelog"
            aria-labelledby="tab-changelog"
            className="h-full overflow-y-auto"
            data-testid="changelog-tab"
          >
            <ChangelogTab />
          </div>
        )}
      </div>

      {/* Footer */}
      <HelpFooter />
    </div>
  );
}

export interface HelpPageContainerAuditInput {
  activeSubTab: string;
  availableSubTabs: string[];
  hasTabSwitchHandler: boolean;
}

export interface HelpPageContainerAuditReport {
  activeSubTabValid: boolean;
  subTabCount: number;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateHelpPageContainerGovernanceAudit(
  input: HelpPageContainerAuditInput,
): HelpPageContainerAuditReport {
  const issueCodes: string[] = [];
  const normalized = input.availableSubTabs
    .map((tab) => tab.trim())
    .filter((tab) => tab.length > 0);
  const subTabCount = new Set(normalized).size;
  if (subTabCount < 3) {
    issueCodes.push('HELP_PAGE_SUBTABS_INCOMPLETE');
  }
  const activeSubTabValid = normalized.includes(input.activeSubTab.trim());
  if (!activeSubTabValid) {
    issueCodes.push('HELP_PAGE_ACTIVE_SUBTAB_INVALID');
  }
  if (!input.hasTabSwitchHandler) {
    issueCodes.push('HELP_PAGE_TAB_SWITCH_HANDLER_MISSING');
  }
  return {
    activeSubTabValid,
    subTabCount,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
