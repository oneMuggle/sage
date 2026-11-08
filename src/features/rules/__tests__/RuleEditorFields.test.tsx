// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { RuleEntry } from '../../../shared/api/rulesApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ConflictNotice } from '../RuleEditorFields';

vi.mock('../../../shared/api/rulesApi', () => ({
  rulesApi: {},
}));

const CONSTRAINT_ENTRY: RuleEntry = {
  id: 'constraint:1',
  layer: 'constraint',
  sourceLabel: '项目规则',
  scope: '全局',
  category: 'coding_style',
  content: '使用双引号',
  enabled: true,
  editable: 'full',
  priority: 5,
  trigger: null,
  updatedAt: 1730000000000,
  origin: null,
};

const DOC_ENTRY: RuleEntry = {
  ...CONSTRAINT_ENTRY,
  id: 'doc:SAGE.md#1',
  layer: 'doc',
  sourceLabel: '项目总纲 SAGE.md',
  category: '提交规范',
  content: '提交前跑 pytest',
  editable: 'full',
  origin: '/tmp/proj/SAGE.md',
};

function renderNotice(props: Omit<React.ComponentProps<typeof ConflictNotice>, 'onUseServer'>) {
  const onUseServer = vi.fn();
  render(
    <I18nProvider defaultLocale="zh">
      <ConflictNotice {...props} onUseServer={onUseServer} />
    </I18nProvider>,
  );
  return { onUseServer };
}

describe('ConflictNotice', () => {
  it('renders trigger, priority and enabled rows for constraint-layer conflicts', () => {
    renderNotice({ current: CONSTRAINT_ENTRY, layer: 'constraint' });
    const block = screen.getByTestId('rule-editor-conflict');
    expect(block).toHaveTextContent('触发词');
    expect(block).toHaveTextContent('优先级');
    expect(block).toHaveTextContent('启用');
  });

  it('renders only category and content rows for doc/global-layer conflicts', () => {
    renderNotice({ current: DOC_ENTRY, layer: 'doc' });
    const block = screen.getByTestId('rule-editor-conflict');
    expect(block).toHaveTextContent('分类');
    expect(block).toHaveTextContent('规则内容');
    expect(block).not.toHaveTextContent('触发词');
    expect(block).not.toHaveTextContent('优先级');
    expect(block).not.toHaveTextContent('启用');
  });

  it('shows an em-dash placeholder when a constraint trigger is null', () => {
    renderNotice({
      current: { ...CONSTRAINT_ENTRY, trigger: null },
      layer: 'constraint',
    });
    const block = screen.getByTestId('rule-editor-conflict');
    expect(block).toHaveTextContent('—');
    expect(block).not.toHaveTextContent('rules.editor.triggerHint');
  });
});
