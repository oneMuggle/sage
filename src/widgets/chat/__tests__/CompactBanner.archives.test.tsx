// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useCompactionArchives } from '../../../entities/chat/compactionArchivesStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import { CompactBanner } from '../CompactBanner';

const INFO = { before: 10, after: 3, removed: 7 };

describe('CompactBanner archives entry', () => {
  beforeEach(() => {
    useCompactionArchives.getState().consume();
  });

  it('requests the archive modal for the message session', () => {
    render(
      <I18nProvider>
        <CompactBanner info={INFO} sessionId="session-1" />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByTestId('compact-banner-open-archives'));
    expect(useCompactionArchives.getState().pendingSessionId).toBe('session-1');
  });

  it('renders no archive button without a session id', () => {
    render(
      <I18nProvider>
        <CompactBanner info={INFO} />
      </I18nProvider>,
    );
    expect(screen.queryByTestId('compact-banner-open-archives')).toBeNull();
  });
});
