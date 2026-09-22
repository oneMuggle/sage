/**
 * R92 — BtwOverlay 统一参考来源展示测试
 *
 * /btw 走同一 /chat/stream 管道，sources_used 到达后写入 btwState；
 * 浮层答案下方应出现可折叠的紧凑来源列表（kind 标签 + 可点击外链）。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useBtwState } from '../../../entities/chat/btwState';
import { I18nProvider } from '../../../shared/lib/i18n';
import { BtwOverlay } from '../BtwOverlay';

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('BtwOverlay — R92 参考来源', () => {
  beforeEach(() => {
    useBtwState.getState().close();
  });

  it('有 sources 时显示可折叠来源开关,展开后含 kind 标签与外链', () => {
    useBtwState.setState({
      isOpen: true,
      question: '顺便问下',
      answer: '答案内容',
      isLoading: false,
      sources: [
        { kind: 'web', title: 'Sage 官网', url: 'https://sage.example.com', snippet: '官网' },
        { kind: 'memory', title: '@memory:火锅 [episodic]', snippet: '爱吃火锅' },
      ],
    });
    renderWithI18n(<BtwOverlay />);

    expect(screen.getByTestId('btw-sources-toggle')).toHaveTextContent('2');
    expect(screen.queryByTestId('btw-sources-list')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('btw-sources-toggle'));
    const list = screen.getByTestId('btw-sources-list');
    expect(list).toHaveTextContent('Sage 官网');
    expect(list).toHaveTextContent('爱吃火锅');
    const link = screen.getByRole('link', { name: 'Sage 官网' });
    expect(link).toHaveAttribute('href', 'https://sage.example.com');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('无 sources 时不渲染来源区块', () => {
    useBtwState.setState({
      isOpen: true,
      question: '顺便问下',
      answer: '答案内容',
      isLoading: false,
      sources: [],
    });
    renderWithI18n(<BtwOverlay />);
    expect(screen.queryByTestId('btw-sources')).not.toBeInTheDocument();
  });

  it('open() 重置上一轮 sources（新一轮 /btw 不残留旧来源）', () => {
    useBtwState.getState().setSources([{ kind: 'web', url: 'https://old.com' }]);
    useBtwState.getState().open('新问题');
    expect(useBtwState.getState().sources).toEqual([]);
  });
});
