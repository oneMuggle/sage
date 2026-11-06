/**
 * DocumentCanvas — 统一文档画布测试。
 *
 * 覆盖：
 *  - 空态渲染 OfficeIntake，有文档时渲染 OfficePreviewPanel；
 *  - 有文档时把文件拖到画布上 → 显示替换遮罩；
 *  - 拖放文件 → onDropFiles 收到操作系统源路径；
 *  - fidelityAvailable / onRefresh / disabled 等透传不丢失。
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../../shared/lib/i18n';
import type { OfficePreviewData } from '../../OfficePreviewPanel';
import { DocumentCanvas } from '../DocumentCanvas';

vi.mock('../../OfficeIntake', () => ({
  OfficeIntake: ({
    onDropFiles,
    disabled,
  }: {
    onDropFiles: (paths: string[]) => void;
    disabled?: boolean;
  }) => (
    <div
      data-testid="office-intake"
      data-disabled={String(Boolean(disabled))}
      onClick={() => onDropFiles(['/tmp/test.docx'])}
    >
      Mock Intake
    </div>
  ),
}));

vi.mock('../../OfficePreviewPanel', () => ({
  OfficePreviewPanel: ({
    preview,
    fidelityAvailable,
    onRefresh,
  }: {
    preview: { data: { summary: { id: string } } } | null;
    fidelityAvailable?: boolean;
    onRefresh?: () => void;
  }) => (
    <div
      data-testid="office-preview-panel"
      data-fidelity={String(fidelityAvailable)}
      data-has-refresh={String(typeof onRefresh === 'function')}
    >
      {preview?.data.summary.id}
    </div>
  ),
}));

/** 造一个带 `path` 的假 File（Electron 21 的拖拽文件带 path）。 */
function makeDroppedFile(name: string, path: string): File {
  const file = new File(['x'], name);
  Object.defineProperty(file, 'path', { value: path, configurable: true });
  return file;
}

function makePreview(id = 'doc1'): OfficePreviewData {
  return {
    docType: 'word',
    data: { summary: { id } },
  } as unknown as OfficePreviewData;
}

function renderCanvas(props: Partial<React.ComponentProps<typeof DocumentCanvas>> = {}) {
  render(
    <I18nProvider defaultLocale="zh">
      <DocumentCanvas preview={null} workspacePath="/tmp/ws" {...props} />
    </I18nProvider>,
  );
}

describe('DocumentCanvas', () => {
  it('renders OfficeIntake when no preview', () => {
    renderCanvas();
    expect(screen.getByTestId('office-document-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('office-intake')).toBeInTheDocument();
    expect(screen.queryByTestId('office-preview-panel')).not.toBeInTheDocument();
  });

  it('renders OfficePreviewPanel when preview exists', () => {
    renderCanvas({ preview: makePreview() });
    expect(screen.getByTestId('office-document-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('office-preview-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('office-intake')).not.toBeInTheDocument();
  });

  it('shows the drop overlay while dragging over a canvas with a preview', () => {
    renderCanvas({ preview: makePreview() });
    const root = screen.getByTestId('office-document-canvas');
    expect(screen.queryByTestId('office-document-canvas-drop-overlay')).not.toBeInTheDocument();

    fireEvent.dragEnter(root, { dataTransfer: { files: [] } });

    expect(screen.getByTestId('office-document-canvas-drop-overlay')).toBeInTheDocument();
    expect(screen.getByText('松开以替换当前文档')).toBeInTheDocument();
  });

  it('replaces the open document when a file with a path is dropped', () => {
    const onDropFiles = vi.fn();
    renderCanvas({ preview: makePreview(), onDropFiles });
    const root = screen.getByTestId('office-document-canvas');

    fireEvent.drop(root, {
      dataTransfer: { files: [makeDroppedFile('dropped.docx', '/tmp/dropped.docx')] },
    });

    expect(onDropFiles).toHaveBeenCalledWith(['/tmp/dropped.docx']);
    expect(screen.queryByTestId('office-document-canvas-drop-overlay')).not.toBeInTheDocument();
  });

  it('does not call onDropFiles when no dropped file carries an OS path', () => {
    const onDropFiles = vi.fn();
    renderCanvas({ preview: makePreview(), onDropFiles });
    const root = screen.getByTestId('office-document-canvas');

    fireEvent.drop(root, { dataTransfer: { files: [new File(['x'], 'web-only.docx')] } });

    expect(onDropFiles).not.toHaveBeenCalled();
  });

  it('forwards fidelityAvailable and onRefresh to OfficePreviewPanel', () => {
    const onRefresh = vi.fn();
    renderCanvas({ preview: makePreview(), fidelityAvailable: false, onRefresh });

    const panel = screen.getByTestId('office-preview-panel');
    expect(panel).toHaveAttribute('data-fidelity', 'false');
    expect(panel).toHaveAttribute('data-has-refresh', 'true');
  });

  it('forwards disabled to OfficeIntake in the empty state', () => {
    renderCanvas({ disabled: true });
    expect(screen.getByTestId('office-intake')).toHaveAttribute('data-disabled', 'true');
  });
});
