import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';

import { NavHistoryProvider } from '../../../app/providers/NavHistoryProvider';
import { useNavigationHistory } from '../useNavigationHistory';

describe('useNavigationHistory', () => {
  it('returns null when used outside NavHistoryProvider', () => {
    let value: ReturnType<typeof useNavigationHistory> = null;
    const Probe = () => {
      value = useNavigationHistory();
      return null;
    };
    render(
      <MemoryRouter>
        <Probe />
      </MemoryRouter>,
    );
    expect(value).toBeNull();
  });

  it('returns context value when used inside NavHistoryProvider', () => {
    let value: ReturnType<typeof useNavigationHistory> = null;
    const Probe = () => {
      value = useNavigationHistory();
      return null;
    };
    render(
      <MemoryRouter initialEntries={['/']}>
        <NavHistoryProvider>
          <Probe />
        </NavHistoryProvider>
      </MemoryRouter>,
    );
    expect(value).not.toBeNull();
    expect(value!.canBack).toBe(false);
  });
});
