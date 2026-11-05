/**
 * OfficeIntake — 统一导入入口测试（Phase 0, plan §M1）。
 *
 * 覆盖：
 *  - 渲染：drop 区 + 支持的扩展名 chip；
 *  - 点击 → onPick（多选对话框由 hook 独占）；
 *  - 键盘 Enter / Space → onPick；
 *  - 拖拽 → onDropFiles 收到操作系统源路径（多文件）；
 *  - 无工作区 / 无文件路径 → 就地报错而不是静默失败；
 *  - disabled → 点击与拖拽都不触发。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { OfficeIntake, OFFICE_INTAKE_EXTENSIONS } from '../OfficeIntake';

/** 造一个带 `path` 的假 File（Electron 21 的拖拽文件带 path，web 不带）。 */
function makeFile(name: string, withPath = true): File {
  const file = new File(['x'], name, { type: 'text/plain' });
  if (withPath) {
    Object.defineProperty(file, 'path', { value: `/tmp/${name}`, configurable: true });
  }
  return file;
}

function renderIntake(props: Partial<React.ComponentProps<typeof OfficeIntake>> = {}) {
  const onPick = vi.fn();
  const onDropFiles = vi.fn();
  render(
    <I18nProvider defaultLocale="zh">
      <OfficeIntake
        workspacePath="/tmp/ws"
        onPick={onPick}
        onDropFiles={onDropFiles}
        {...props}
      />
    </I18nProvider>,
  );
  return { onPick, onDropFiles };
}

describe('OfficeIntake — 统一导入入口', () => {
  it('renders the drop zone with every supported extension chip', () => {
    renderIntake();
    expect(screen.getByTestId('office-intake')).toBeInTheDocument();
    for (const ext of OFFICE_INTAKE_EXTENSIONS) {
      expect(screen.getByText(`.${ext}`)).toBeInTheDocument();
    }
  });

  it('triggers onPick when the drop zone is clicked', async () => {
    const { onPick } = renderIntake();
    fireEvent.click(screen.getByTestId('office-intake-pick'));
    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1));
  });

  it('triggers onPick via the keyboard (Enter)', async () => {
    const { onPick } = renderIntake();
    fireEvent.keyDown(screen.getByTestId('office-intake'), { key: 'Enter' });
    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1));
  });

  it('triggers onPick via the keyboard (Space)', async () => {
    const { onPick } = renderIntake();
    fireEvent.keyDown(screen.getByTestId('office-intake'), { key: ' ' });
    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1));
  });

  it('passes every dropped file path to onDropFiles', async () => {
    const { onDropFiles } = renderIntake();
    fireEvent.drop(screen.getByTestId('office-intake'), {
      dataTransfer: { files: [makeFile('a.docx'), makeFile('b.xlsx')] },
    });
    await waitFor(() => {
      expect(onDropFiles).toHaveBeenCalledWith(['/tmp/a.docx', '/tmp/b.xlsx']);
    });
  });

  it('shows an error and does not import when no workspace is bound', async () => {
    const { onPick, onDropFiles } = renderIntake({ workspacePath: null });
    fireEvent.click(screen.getByTestId('office-intake-pick'));
    expect(await screen.findByTestId('office-intake-error')).toBeInTheDocument();
    expect(onPick).not.toHaveBeenCalled();

    fireEvent.drop(screen.getByTestId('office-intake'), {
      dataTransfer: { files: [makeFile('a.docx')] },
    });
    expect(onDropFiles).not.toHaveBeenCalled();
  });

  it('shows an error when the dropped files carry no OS path (web)', async () => {
    const { onDropFiles } = renderIntake();
    fireEvent.drop(screen.getByTestId('office-intake'), {
      dataTransfer: { files: [makeFile('a.docx', false)] },
    });
    expect(await screen.findByTestId('office-intake-error')).toBeInTheDocument();
    expect(onDropFiles).not.toHaveBeenCalled();
  });

  it('ignores clicks and drops while disabled', async () => {
    const { onPick, onDropFiles } = renderIntake({ disabled: true });
    fireEvent.click(screen.getByTestId('office-intake-pick'));
    fireEvent.drop(screen.getByTestId('office-intake'), {
      dataTransfer: { files: [makeFile('a.docx')] },
    });
    expect(onPick).not.toHaveBeenCalled();
    expect(onDropFiles).not.toHaveBeenCalled();
  });
});
