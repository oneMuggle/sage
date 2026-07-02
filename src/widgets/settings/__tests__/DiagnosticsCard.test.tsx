// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DiagnosticsCard } from '../DiagnosticsCard';

const mockElectronAPI = {
  listLogFiles: vi.fn(),
  openLogDir: vi.fn(),
  copyLogPath: vi.fn(),
  cleanupLogs: vi.fn(),
  setLogLevel: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  (window as unknown as { electronAPI: typeof mockElectronAPI }).electronAPI = mockElectronAPI;
});

describe('DiagnosticsCard', () => {
  it('renders log file list', async () => {
    mockElectronAPI.listLogFiles.mockResolvedValue([
      { name: 'sage-2026-07-02.ndjson', sizeBytes: 12345, mtimeMs: Date.now() },
    ]);
    render(<DiagnosticsCard />);
    await waitFor(() => {
      expect(screen.getByText(/sage-2026-07-02\.ndjson/)).toBeInTheDocument();
    });
  });

  it('triggers openLogDir on button click', async () => {
    mockElectronAPI.listLogFiles.mockResolvedValue([]);
    mockElectronAPI.openLogDir.mockResolvedValue('/path/to/logs');
    render(<DiagnosticsCard />);
    const btn = await screen.findByRole('button', { name: /打开日志目录/ });
    fireEvent.click(btn);
    expect(mockElectronAPI.openLogDir).toHaveBeenCalled();
  });

  it('triggers setLogLevel when level changes', async () => {
    mockElectronAPI.listLogFiles.mockResolvedValue([]);
    mockElectronAPI.setLogLevel.mockResolvedValue({ ok: true });
    render(<DiagnosticsCard />);
    const select = await screen.findByRole('combobox', { name: /日志级别/ });
    fireEvent.change(select, { target: { value: 'debug' } });
    await waitFor(() => {
      expect(mockElectronAPI.setLogLevel).toHaveBeenCalledWith('debug');
    });
  });
});
