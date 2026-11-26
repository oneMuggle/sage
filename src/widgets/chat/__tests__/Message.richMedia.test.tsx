// P1 (2026-11-25): 工具卡消费 richMedia（URL-only 富媒体引用）。
// 可交互 SVG → SvgDiagramViewer；其余 → MediaAttachment；与 mediaRefs 同 id 去重。

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { Message as MessageType, ToolCall } from '../../../shared/lib/store';
import { Message } from '../Message';

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

function assistantMsg(tool_calls: MessageType['tool_calls']): MessageType {
  return {
    id: 'a',
    session_id: 's',
    role: 'assistant',
    content: '',
    created_at: 0,
    tool_calls,
  };
}

const svgEnvelope = JSON.stringify({
  text: 'ok',
  metadata: {
    richMedia: [
      {
        id: 'm1',
        kind: 'diagram',
        mime_type: 'image/svg+xml',
        api_url: '/api/v1/media/m1',
        interactive: true,
      },
    ],
  },
});

describe('Message 渲染 richMedia（P1）', () => {
  it('renders interactive svg via SvgDiagramViewer', () => {
    const tc: ToolCall = {
      id: 't1',
      name: 'mcp__drawio__render_diagram',
      args: {},
      result: svgEnvelope,
    };
    renderWithI18n(<Message message={assistantMsg([tc])} />);
    expect(screen.getByTestId('svg-diagram-img')).toBeTruthy();
    expect(screen.getByTestId('svg-diagram-download-svg')).toBeTruthy();
  });

  it('renders non-interactive media via MediaAttachment', () => {
    const envelope = JSON.stringify({
      text: 'ok',
      metadata: {
        richMedia: [
          {
            id: 'm2',
            kind: 'image',
            mime_type: 'image/png',
            api_url: '/api/v1/media/m2',
            title: '生成图',
          },
        ],
      },
    });
    const tc: ToolCall = { id: 't2', name: 'image_gen', args: {}, result: envelope };
    renderWithI18n(<Message message={assistantMsg([tc])} />);
    expect(screen.getByAltText('生成图')).toBeTruthy();
    expect(screen.queryByTestId('svg-diagram-img')).toBeNull();
  });

  it('skips richMedia entries already covered by mediaRefs (same id)', () => {
    const envelope = JSON.stringify({
      text: 'ok',
      metadata: {
        mediaRefs: [
          { id: 'm3', kind: 'image', mime_type: 'image/png', api_url: '/api/v1/media/m3' },
        ],
        richMedia: [
          {
            id: 'm3',
            kind: 'image',
            mime_type: 'image/png',
            api_url: '/api/v1/media/m3',
            title: 'dup',
          },
        ],
      },
    });
    const tc: ToolCall = { id: 't3', name: 'image_gen', args: {}, result: envelope };
    renderWithI18n(<Message message={assistantMsg([tc])} />);
    expect(screen.queryByAltText('dup')).toBeNull();
    expect(screen.getAllByRole('img')).toHaveLength(1);
  });
});
