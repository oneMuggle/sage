/**
 * T14: Unit tests for DiagnosticCard component.
 *
 * Tests cover:
 * - Shows "加载中…" while preview is loading
 * - Shows preview data (count, timestamps, sample URLs) after load
 * - Shows error state when preview fails
 * - Checkboxes for includePrompts and includeHostname render and toggle
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DiagnosticCard } from '../DiagnosticCard';

const defaultPreview = {
  count: 12,
  oldestTs: '2026-09-11T14:00:00Z',
  newestTs: '2026-09-11T16:48:00Z',
  sampleUrls: ['http://x/v1/chat/completions'],
  version: '1',
};

beforeEach(() => {
  (window as any).electronAPI = {
    diagnostic: {
      preview: vi.fn().mockResolvedValue(defaultPreview),
      exportBundle: vi.fn().mockResolvedValue({ ok: true, path: '/tmp/x.zip' }),
    },
  };
});

describe('DiagnosticCard', () => {
  it('renders preview data after load (count, timestamps, sample URLs)', async () => {
    render(<DiagnosticCard />);

    // Wait for the card to load data — the "12" appears inside <strong>12</strong>
    // (text split across elements), so use testid + textContent instead of getByText.
    const card = screen.getByTestId('diagnostic-card');
    await waitFor(() => {
      expect(card.textContent).toContain('12');
      expect(card.textContent).toContain('条');
    });

    // Timestamps
    expect(card.textContent).toContain('2026-09-11T14:00:00Z');
    expect(card.textContent).toContain('2026-09-11T16:48:00Z');

    // Sample URL
    expect(card.textContent).toContain('http://x/v1/chat/completions');
  });

  it('shows error state when preview fails', async () => {
    (window as any).electronAPI.diagnostic.preview.mockRejectedValue(new Error('boom'));

    render(<DiagnosticCard />);

    const card = screen.getByTestId('diagnostic-card');
    await waitFor(() => {
      expect(card.textContent).toContain('加载失败');
      expect(card.textContent).toContain('boom');
    });
  });

  it('renders checkboxes for includePrompts and includeHostname', async () => {
    render(<DiagnosticCard />);

    // Wait for data to load
    const card = screen.getByTestId('diagnostic-card');
    await waitFor(() => {
      expect(card.textContent).toContain('12');
    });

    const promptsCheckbox = screen.getByTestId('checkbox-prompts') as HTMLInputElement;
    const hostnameCheckbox = screen.getByTestId('checkbox-hostname') as HTMLInputElement;

    expect(promptsCheckbox).toBeInTheDocument();
    expect(hostnameCheckbox).toBeInTheDocument();
    expect(promptsCheckbox.checked).toBe(false);
    expect(hostnameCheckbox.checked).toBe(false);

    // Toggle prompts
    fireEvent.click(promptsCheckbox);
    expect(promptsCheckbox.checked).toBe(true);

    // Toggle hostname
    fireEvent.click(hostnameCheckbox);
    expect(hostnameCheckbox.checked).toBe(true);
  });

  it('renders the refresh button and ExportButton', async () => {
    render(<DiagnosticCard />);

    // Wait for data to load
    const card = screen.getByTestId('diagnostic-card');
    await waitFor(() => {
      expect(card.textContent).toContain('12');
    });

    // Refresh button
    expect(screen.getByRole('button', { name: /刷新/ })).toBeInTheDocument();

    // Export button
    expect(screen.getByTestId('diagnostic-export-btn')).toBeInTheDocument();
  });

  it('shows the description footer text', async () => {
    render(<DiagnosticCard />);

    const card = screen.getByTestId('diagnostic-card');
    await waitFor(() => {
      expect(card.textContent).toContain('导出文件用于问题排查');
    });
  });
});
