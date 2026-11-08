import { fireEvent, render, screen } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { PatchOperation } from '../../../shared/api/rulesApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { PatchCard } from '../PatchCard';

const UPDATE_OP: PatchOperation = {
  opId: 'op-1',
  action: 'update',
  layer: 'constraint',
  ruleId: 'constraint:1',
  before: { content: '使用单引号' },
  after: { content: '使用双引号' },
  reason: '统一风格',
  expectedUpdatedAt: 1730000000000,
  error: null,
};

function renderCard(
  operation: PatchOperation,
  props: Partial<ComponentProps<typeof PatchCard>> = {},
) {
  return render(
    <I18nProvider defaultLocale="zh">
      <PatchCard operation={operation} selected {...props} />
    </I18nProvider>,
  );
}

describe('PatchCard', () => {
  it('renders layer, action, reason and before/after content', () => {
    renderCard(UPDATE_OP);
    expect(screen.getByTestId('patch-card-op-1')).toBeInTheDocument();
    expect(screen.getByText('修改')).toBeInTheDocument();
    expect(screen.getByTestId('patch-before-op-1')).toHaveTextContent('使用单引号');
    expect(screen.getByTestId('patch-after-op-1')).toHaveTextContent('使用双引号');
    expect(screen.getByText(/统一风格/)).toBeInTheDocument();
    expect(screen.getByTestId('patch-select-op-1')).toHaveAttribute(
      'aria-label',
      '修改 · constraint:1',
    );
  });

  it('disables the checkbox for any operation that cannot be applied', () => {
    renderCard({ ...UPDATE_OP, error: 'rule_not_found' }, { selected: false });
    expect(screen.getByTestId('patch-select-op-1')).toBeDisabled();
    expect(screen.getByTestId('patch-error-op-1')).toHaveTextContent('规则不存在或已变更');
  });

  it('disables selection and offers playbook navigation for readonly layers', () => {
    const onOpenPlaybook = vi.fn();
    renderCard(
      { ...UPDATE_OP, layer: 'playbook', error: 'readonly_layer' },
      { selected: false, onOpenPlaybook },
    );
    expect(screen.getByTestId('patch-select-op-1')).toBeDisabled();
    expect(screen.getByTestId('patch-error-op-1')).toHaveTextContent('规程规则只读');
    fireEvent.click(screen.getByTestId('patch-open-playbook-op-1'));
    expect(onOpenPlaybook).toHaveBeenCalledTimes(1);
  });

  it('shows the current value when apply reports a conflict', () => {
    renderCard(UPDATE_OP, {
      result: {
        opId: 'op-1',
        status: 'conflict',
        message: '规则已被修改',
        current: { content: '当前内容' },
      },
    });
    expect(screen.getByTestId('patch-result-op-1')).toHaveTextContent('冲突');
    expect(screen.getByTestId('patch-current-op-1')).toHaveTextContent('当前内容');
  });

  it('warns that delete operations are not selected by default', () => {
    renderCard(
      { ...UPDATE_OP, action: 'delete', after: {}, reason: '与其他规则重复' },
      {
        selected: false,
      },
    );
    expect(screen.getByText('删除')).toBeInTheDocument();
    expect(screen.getByText('删除不可撤销，默认未选中。')).toBeInTheDocument();
  });

  it('reports checkbox changes with the operation id', () => {
    const onToggle = vi.fn();
    renderCard(UPDATE_OP, { selected: false, onToggle });
    fireEvent.click(screen.getByTestId('patch-select-op-1'));
    expect(onToggle).toHaveBeenCalledWith('op-1', true);
  });
});
