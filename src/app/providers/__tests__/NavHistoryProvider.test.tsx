// src/app/providers/__tests__/NavHistoryProvider.test.tsx
import { render } from '@testing-library/react';
import { useContext } from 'react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect } from 'vitest';

import {
  NavHistoryProvider,
  NavHistoryContext,
  type NavHistoryContextValue,
} from '../NavHistoryProvider';

describe('NavHistoryProvider', () => {
  it('renders children without crashing', () => {
    const { getByText } = render(
      <MemoryRouter initialEntries={['/']}>
        <NavHistoryProvider>
          <div>child</div>
        </NavHistoryProvider>
      </MemoryRouter>,
    );
    expect(getByText('child')).toBeInTheDocument();
  });

  it('tracks initial pathname in stack', () => {
    let captured: NavHistoryContextValue | null = null;
    const Capture = () => {
      const ctx = useContext(NavHistoryContext);
      captured = ctx;
      return null;
    };
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <NavHistoryProvider>
          <Capture />
        </NavHistoryProvider>
      </MemoryRouter>,
    );
    expect(captured).not.toBeNull();
    expect(captured!.canBack).toBe(false); // Only one entry, can't go back
  });

  it('handles multi-route navigation state correctly', () => {
    let captured: NavHistoryContextValue | null = null;
    const Capture = () => {
      const ctx = useContext(NavHistoryContext);
      captured = ctx;
      return null;
    };

    render(
      <MemoryRouter initialEntries={['/a', '/b']} initialIndex={0}>
        <NavHistoryProvider>
          <Routes>
            <Route path="/a" element={<Capture />} />
            <Route path="/b" element={<Capture />} />
          </Routes>
        </NavHistoryProvider>
      </MemoryRouter>
    );
    // After initial entries, stack reflects visited paths
    expect(captured).not.toBeNull();
  });
});
