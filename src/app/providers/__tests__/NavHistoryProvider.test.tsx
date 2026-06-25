// src/app/providers/__tests__/NavHistoryProvider.test.tsx
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';

import { NavHistoryProvider } from '../NavHistoryProvider';

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
});
