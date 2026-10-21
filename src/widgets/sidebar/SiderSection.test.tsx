import { fireEvent, render, screen } from '@testing-library/react';
import type { LucideIcon, LucideProps } from 'lucide-react';
import { describe, it, expect } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';

import {
  SiderSection,
  formatSiderSectionAuditJson,
  formatSiderSectionAuditSnapshot,
} from './SiderSection';

// Mock LucideIcon 组件用于测试
function MockIcon(_props: LucideProps) {
  return <svg data-testid="mock-icon" />;
}

describe('SiderSection', () => {
  it('renders its label and a collapse toggle', () => {
    render(
      <I18nProvider>
        <SiderSection
          sectionKey="conversations"
          label="会话"
          icon={MockIcon as LucideIcon}
          collapsed={false}
          onToggleCollapsed={() => {}}
          render={() => <div>content</div>}
        />
      </I18nProvider>,
    );
    expect(screen.getByText('会话')).toBeInTheDocument();
    expect(screen.getByText('content')).toBeInTheDocument();
  });

  it('formats audit snapshot and JSON and supports copy controls (Phase P100)', () => {
    expect(
      formatSiderSectionAuditSnapshot({
        sectionKey: 'projects',
        label: '项目',
        collapsed: true,
        hasTrailing: true,
        maxHeight: '240px',
      }),
    ).toBe('siderSection|key=projects|label=项目|collapsed=1|trailing=1|maxH=240px');
    expect(formatSiderSectionAuditSnapshot({})).toBe(
      'siderSection|key=none|label=none|collapsed=0|trailing=0|maxH=auto',
    );
    expect(
      JSON.parse(
        formatSiderSectionAuditJson({
          sectionKey: 'conversations',
          label: '会话',
          collapsed: false,
          hasTrailing: false,
        }),
      ),
    ).toEqual({
      sectionKey: 'conversations',
      label: '会话',
      collapsed: false,
      hasTrailing: false,
      maxHeight: 'auto',
    });

    render(
      <I18nProvider>
        <SiderSection
          sectionKey="conversations"
          label="会话"
          icon={MockIcon as LucideIcon}
          collapsed={false}
          onToggleCollapsed={() => {}}
          render={() => <div>content</div>}
        />
      </I18nProvider>,
    );
    const snapBtn = screen.getByTestId('sider-section-copy-snapshot');
    const jsonBtn = screen.getByTestId('sider-section-copy-json');
    fireEvent.click(snapBtn);
    expect(snapBtn).toHaveTextContent('已复制快照');
    fireEvent.click(jsonBtn);
    expect(jsonBtn).toHaveTextContent('已复制JSON');
  });
});
