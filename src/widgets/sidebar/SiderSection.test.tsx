import { render, screen } from '@testing-library/react';
import type { LucideIcon, LucideProps } from 'lucide-react';
import { describe, it, expect } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';

import { SiderSection } from './SiderSection';

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
});
