import { render, screen } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import { ThemeErrorBoundary } from '../ErrorBoundary';

function ThrowingChild(): JSX.Element {
  throw new Error('boom');
}

function GoodChild(): JSX.Element {
  return <div>good</div>;
}

describe('ThemeErrorBoundary', () => {
  const originalError = console.error;
  beforeAll(() => {
    console.error = vi.fn();
  });
  afterAll(() => {
    console.error = originalError;
  });

  it('renders children when no error', () => {
    render(
      <ThemeErrorBoundary>
        <GoodChild />
      </ThemeErrorBoundary>,
    );
    expect(screen.getByText('good')).toBeTruthy();
  });

  it('renders default fallback when child throws', () => {
    render(
      <ThemeErrorBoundary>
        <ThrowingChild />
      </ThemeErrorBoundary>,
    );
    expect(screen.getByTestId('theme-fallback')).toBeTruthy();
    expect(screen.getByText(/默认/)).toBeTruthy();
  });

  it('renders custom fallback when provided', () => {
    render(
      <ThemeErrorBoundary fallback={<div>custom fallback</div>}>
        <ThrowingChild />
      </ThemeErrorBoundary>,
    );
    expect(screen.getByText('custom fallback')).toBeTruthy();
  });
});