/**
 * OfficeFilePicker — Task 6 fix tests (2026-07-24).
 *
 * The picker is now a pure interaction surface: it delegates the full
 * import + read lifecycle to the hook via two callbacks and no longer
 * touches the Electron gateway itself.
 *
 * Coverage:
 * 1. clicking the picker calls `onPick`
 * 2. clicking a disabled picker does NOT call `onPick`
 * 3. clicking with no workspace shows an error and does NOT call `onPick`
 * 4. dropping a legacy `.doc`/`.xls`/`.ppt` file shows an error and does
 *    NOT call `onDropFile`
 * 5. dropping a modern `.xlsx` file calls `onDropFile` with the OS source path
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { OfficeFilePicker } from '../OfficeFilePicker';

describe('OfficeFilePicker — delegates to the hook', () => {
  it('clicking the picker calls onPick', async () => {
    const onPick = vi.fn().mockResolvedValue(undefined);
    const onDropFile = vi.fn();

    render(
      <OfficeFilePicker
        docType="ppt"
        workspacePath="/tmp/ws"
        onPick={onPick}
        onDropFile={onDropFile}
      />,
    );

    fireEvent.click(screen.getByTestId('office-file-picker-ppt'));

    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1));
    expect(onDropFile).not.toHaveBeenCalled();
  });

  it('clicking a disabled picker does NOT call onPick', async () => {
    const onPick = vi.fn();
    const onDropFile = vi.fn();

    render(
      <OfficeFilePicker
        docType="word"
        workspacePath="/tmp/ws"
        onPick={onPick}
        onDropFile={onDropFile}
        disabled
      />,
    );

    fireEvent.click(screen.getByTestId('office-file-picker-word'));

    // Give any (erroneous) async handler a tick to run before asserting.
    await Promise.resolve();
    expect(onPick).not.toHaveBeenCalled();
  });

  it('clicking with no workspace shows an error and does NOT call onPick', async () => {
    const onPick = vi.fn();
    const onDropFile = vi.fn();

    render(
      <OfficeFilePicker
        docType="excel"
        workspacePath={null}
        onPick={onPick}
        onDropFile={onDropFile}
      />,
    );

    fireEvent.click(screen.getByTestId('office-file-picker-excel'));

    await waitFor(() => {
      expect(screen.getByText(/请先选择工作区/)).toBeInTheDocument();
    });
    expect(onPick).not.toHaveBeenCalled();
  });

  it('dropping a legacy .doc/.xls/.ppt file shows an error and does NOT call onDropFile', async () => {
    const onPick = vi.fn();
    const onDropFile = vi.fn();

    render(
      <OfficeFilePicker
        docType="word"
        workspacePath="/tmp/ws"
        onPick={onPick}
        onDropFile={onDropFile}
      />,
    );

    const picker = screen.getByTestId('office-file-picker-word');
    // jsdom does not populate File.path; we simulate the Electron-provided
    // path to exercise the legacy-extension rejection branch.
    const fakeFile = Object.assign(
      new File(['binary'], 'legacy.doc', { type: 'application/msword' }),
      { path: '/tmp/legacy.doc' },
    );
    const dt = { files: [fakeFile] } as unknown as DataTransfer;
    fireEvent.drop(picker, { dataTransfer: dt });

    await waitFor(() => {
      expect(screen.getByText(/不支持的格式/)).toBeInTheDocument();
    });
    expect(onDropFile).not.toHaveBeenCalled();
    expect(onPick).not.toHaveBeenCalled();
  });

  it('dropping a modern .xlsx file calls onDropFile with the OS source path', async () => {
    const onPick = vi.fn();
    const onDropFile = vi.fn().mockResolvedValue(undefined);

    render(
      <OfficeFilePicker
        docType="excel"
        workspacePath="/tmp/ws"
        onPick={onPick}
        onDropFile={onDropFile}
      />,
    );

    const picker = screen.getByTestId('office-file-picker-excel');
    const fakeFile = Object.assign(
      new File(['binary'], 'sheet.xlsx', {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
      { path: '/tmp/sheet.xlsx' },
    );
    const dt = { files: [fakeFile] } as unknown as DataTransfer;
    fireEvent.drop(picker, { dataTransfer: dt });

    await waitFor(() => expect(onDropFile).toHaveBeenCalledWith('/tmp/sheet.xlsx'));
    expect(onPick).not.toHaveBeenCalled();
  });
});
