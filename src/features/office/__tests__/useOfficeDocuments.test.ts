/**
 * useOfficeDocuments — Task 6 fix tests (2026-07-24).
 *
 * Focus: the import-token lifecycle owned by the hook.
 *   - success  → `completeOfficeImport(importToken)`
 *   - read fail → `discardOfficeImport(importToken)` (the `safeDiscard` path)
 *   - cancel   → returns `null`, no complete/discard
 *
 * The I1 review finding: `safeDiscard` had no vitest coverage. The core
 * case here resolves the pick, rejects the read, and asserts the staged
 * import is discarded with the token.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockListDocuments = vi.fn();
const mockReadPpt = vi.fn();
vi.mock('../../../shared/api/officeApi', () => ({
  officeApi: {
    listDocuments: (...args: unknown[]) => mockListDocuments(...args),
    readPpt: (...args: unknown[]) => mockReadPpt(...args),
    readWord: vi.fn(),
    readExcel: vi.fn(),
  },
}));

import { useOfficeDocuments } from '../useOfficeDocuments';

const mockPickAndImport = vi.fn();
const mockCompleteImport = vi.fn();
const mockDiscardImport = vi.fn();

interface FakeWindow {
  electronAPI?: {
    office: {
      pickAndImportOfficeFile: typeof mockPickAndImport;
      completeOfficeImport: typeof mockCompleteImport;
      discardOfficeImport: typeof mockDiscardImport;
    };
  };
}

const IMPORT_PAYLOAD = {
  workspacePath: '/tmp/ws',
  docType: 'ppt' as const,
  documentId: 'tok-1',
  filename: 'deck.pptx',
  managedPath: '/tmp/ws/office/ppt/tok-1/deck.pptx',
  originalName: 'deck.pptx',
  sizeBytes: 1024,
  importToken: 'tok-1',
};

beforeEach(() => {
  mockListDocuments.mockReset();
  mockReadPpt.mockReset();
  mockPickAndImport.mockReset();
  mockCompleteImport.mockReset();
  mockDiscardImport.mockReset();
  mockListDocuments.mockResolvedValue({ documents: [] });
  mockCompleteImport.mockResolvedValue(undefined);
  mockDiscardImport.mockResolvedValue(undefined);
  (window as unknown as FakeWindow).electronAPI = {
    office: {
      pickAndImportOfficeFile: mockPickAndImport,
      completeOfficeImport: mockCompleteImport,
      discardOfficeImport: mockDiscardImport,
    },
  };
});

afterEach(() => {
  delete (window as unknown as FakeWindow).electronAPI;
});

describe('useOfficeDocuments — importAndRead token lifecycle', () => {
  it('discards the staged import with importToken when the read fails (safeDiscard)', async () => {
    mockPickAndImport.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockRejectedValueOnce(new Error('parse failed'));

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    await act(async () => {
      await expect(result.current.importAndRead('ppt')).rejects.toThrow('parse failed');
    });

    expect(mockDiscardImport).toHaveBeenCalledWith('tok-1');
    expect(mockCompleteImport).not.toHaveBeenCalled();
  });

  it('swallows a discard failure so the read error still surfaces', async () => {
    mockPickAndImport.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockRejectedValueOnce(new Error('parse failed'));
    mockDiscardImport.mockRejectedValueOnce(new Error('discard blew up'));

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    await act(async () => {
      // The read error — not the discard error — is what propagates.
      await expect(result.current.importAndRead('ppt')).rejects.toThrow('parse failed');
    });

    expect(mockDiscardImport).toHaveBeenCalledWith('tok-1');
  });

  it('completes the import (not discard) when the read succeeds', async () => {
    mockPickAndImport.mockResolvedValueOnce(IMPORT_PAYLOAD);
    mockReadPpt.mockResolvedValueOnce({ slides: [], summary: 'ok' });

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    let read: unknown;
    await act(async () => {
      read = await result.current.importAndRead('ppt');
    });

    expect(read).toEqual({ slides: [], summary: 'ok' });
    expect(mockCompleteImport).toHaveBeenCalledWith('tok-1');
    expect(mockDiscardImport).not.toHaveBeenCalled();
  });

  it('returns null and touches neither complete nor discard on user cancel', async () => {
    mockPickAndImport.mockResolvedValueOnce(undefined); // dialog cancelled

    const { result } = renderHook(() => useOfficeDocuments('/tmp/ws'));
    await waitFor(() => expect(mockListDocuments).toHaveBeenCalled());

    let read: unknown = 'sentinel';
    await act(async () => {
      read = await result.current.importAndRead('ppt');
    });

    expect(read).toBeNull();
    expect(mockReadPpt).not.toHaveBeenCalled();
    expect(mockCompleteImport).not.toHaveBeenCalled();
    expect(mockDiscardImport).not.toHaveBeenCalled();
  });
});
