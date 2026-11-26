// 2026-11-26: 端点故障转移提示横幅（kind=failover）。
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { RetryInfo } from '../../../shared/api';
import { I18nProvider } from '../../../shared/lib/i18n';
import { RetryBanner } from '../RetryBanner';

function renderBanner(info: RetryInfo, locale: 'zh' | 'en' = 'zh') {
  return render(
    <I18nProvider defaultLocale={locale}>
      <RetryBanner info={info} />
    </I18nProvider>,
  );
}

describe('RetryBanner failover', () => {
  it('renders endpoint switch notice without attempt counter', () => {
    const { getByTestId, queryByTestId } = renderBanner({
      kind: 'failover',
      attempt: 0,
      max_attempts: 0,
      error_type: 'timeout',
      error_message: '',
      delay: 0,
      from_endpoint_name: 'Primary',
      to_endpoint_name: 'Backup',
    });
    const banner = getByTestId('failover-banner');
    expect(banner.textContent).toContain('Backup');
    expect(banner.textContent).toContain('Primary');
    expect(queryByTestId('retry-banner')).toBeNull();
  });

  it('falls back to endpoint ids when names are missing', () => {
    const { getByTestId } = renderBanner({
      kind: 'failover',
      attempt: 0,
      max_attempts: 0,
      error_type: 'server_error',
      error_message: '',
      delay: 0,
      from_endpoint: 'ep-a',
      to_endpoint: 'ep-b',
    });
    const banner = getByTestId('failover-banner');
    expect(banner.textContent).toContain('ep-b');
    expect(banner.textContent).toContain('ep-a');
  });
});
