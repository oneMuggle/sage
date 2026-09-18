// src/widgets/chat/__tests__/Message.artifacts.test.tsx
//
// right-panel R1 批次 B: 消息内联产物 chip —— 命中 tool_call_id 渲染、
// 点击 selectArtifact 直达面板预览、未命中不渲染。

import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { Artifact } from '../../../features/artifacts/artifactApi';
import { useRightPanelStore } from '../../../features/right-panel/rightPanelStore';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType } from '../../../shared/lib/store';
import { Message } from '../Message';

const art: Artifact = {
  id: 'art-9',
  session_id: 's',
  tool_call_id: 'tc-9',
  path: '/tmp/report.md',
  name: 'report.md',
  kind: 'markdown',
  size: 10,
  created_at: 1,
};

const msg: MessageType = {
  id: 'm1',
  session_id: 's',
  role: 'assistant',
  content: '已生成文件',
  created_at: 0,
  tool_calls: [{ id: 'tc-9', name: 'write_file', args: { path: '/tmp/report.md' } }],
};

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

beforeEach(() => {
  useRightPanelStore.setState({
    open: false,
    tab: 'progress',
    maximized: false,
    selectedArtifactId: null,
    seenArtifactCount: {},
  });
});

describe('Message 内联产物 chip（right-panel R1）', () => {
  it('命中 tool_call_id 时渲染 chip，点击直达面板预览', () => {
    renderWithI18n(
      <Message message={msg} artifactsByToolCall={{ 'tc-9': [art] }} />,
    );
    const chip = screen.getByTestId('message-artifact-chip');
    expect(chip).toHaveTextContent('report.md');
    fireEvent.click(chip);
    const s = useRightPanelStore.getState();
    expect(s.open).toBe(true);
    expect(s.tab).toBe('artifacts');
    expect(s.selectedArtifactId).toBe('art-9');
  });

  it('无命中映射时不渲染 chip', () => {
    renderWithI18n(<Message message={msg} artifactsByToolCall={{}} />);
    expect(screen.queryByTestId('message-artifact-chip')).not.toBeInTheDocument();
  });
});
