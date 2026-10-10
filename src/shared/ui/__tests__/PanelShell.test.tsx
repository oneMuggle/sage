import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// 走 barrel 导入：验证 shared/ui 的对外出口可用（批次 B/C 的面板都从这里取）
import { PanelShell, PanelShellAction } from '../index';

describe('PanelShell', () => {
  it('无 tabs 时渲染标题', () => {
    render(
      <PanelShell title="深度研究" testId="shell">
        <p>内容</p>
      </PanelShell>,
    );
    expect(screen.getByTestId('panel-shell-header')).toBeInTheDocument();
    expect(screen.getByTestId('panel-shell-header').className).toContain('h-12');
    expect(screen.getByText('深度研究')).toBeInTheDocument();
    expect(screen.getByText('内容')).toBeInTheDocument();
  });

  it('tabs 模式渲染全部标签并回调切换', () => {
    const onTabChange = vi.fn();
    render(
      <PanelShell
        tabs={[
          { id: 'progress', label: '进度' },
          { id: 'artifacts', label: '产物' },
        ]}
        activeTab="progress"
        onTabChange={onTabChange}
      >
        <p>内容</p>
      </PanelShell>,
    );

    expect(screen.getByTestId('panel-shell-tab-progress')).toHaveAttribute('aria-current', 'true');
    expect(screen.getByTestId('panel-shell-tab-artifacts')).toHaveAttribute(
      'aria-current',
      'false',
    );
    fireEvent.click(screen.getByTestId('panel-shell-tab-artifacts'));
    expect(onTabChange).toHaveBeenCalledWith('artifacts');
  });

  it('count > 0 时标签显示计数徽标', () => {
    render(
      <PanelShell
        tabs={[
          { id: 'artifacts', label: '产物', count: 3 },
          { id: 'changes', label: '变更', count: 0 },
        ]}
        activeTab="artifacts"
        onTabChange={vi.fn()}
      >
        <p>内容</p>
      </PanelShell>,
    );
    expect(screen.getByText('产物 (3)')).toBeInTheDocument();
    // count 为 0 不显示 "(0)"，避免"没有变更"被读成"变更 0 条"
    expect(screen.getByText('变更')).toBeInTheDocument();
  });

  it('actions 槽独立于 tabs 渲染', () => {
    render(
      <PanelShell
        title="终端"
        actions={<button type="button">最大化</button>}
      >
        <p>内容</p>
      </PanelShell>,
    );
    expect(screen.getByRole('button', { name: '最大化' })).toBeInTheDocument();
  });

  it('无标题/无 tabs/无 actions 时不渲染空头部', () => {
    render(
      <PanelShell>
        <p>内容</p>
      </PanelShell>,
    );
    expect(screen.queryByTestId('panel-shell-header')).toBeNull();
  });

  it('empty 时以统一空态替代内容', () => {
    render(
      <PanelShell empty emptyLabel="从变更卡片点击「预览」打开文档">
        <p>不该出现的内容</p>
      </PanelShell>,
    );
    expect(screen.getByText('从变更卡片点击「预览」打开文档')).toBeInTheDocument();
    expect(screen.queryByText('不该出现的内容')).toBeNull();
  });

  it('仅在传入 resize 回调时渲染边缘手柄', () => {
    const onMouseDown = vi.fn();
    const { rerender } = render(
      <PanelShell title="右栏">
        <p>内容</p>
      </PanelShell>,
    );
    expect(screen.queryByTestId('panel-shell-resize-handle')).toBeNull();

    rerender(
      <PanelShell
        title="右栏"
        onResizeMouseDown={onMouseDown}
        onResizeDoubleClick={vi.fn()}
        onResizeKeyDown={vi.fn()}
      >
        <p>内容</p>
      </PanelShell>,
    );
    const handle = screen.getByTestId('panel-shell-resize-handle');
    expect(handle).toHaveAttribute('aria-orientation', 'vertical');
    fireEvent.mouseDown(handle);
    expect(onMouseDown).toHaveBeenCalled();
  });

  it('PanelShellAction 满足 28px 热区下限且必带可访问标签', () => {
    // 现状 chat 右栏的档位按钮是 w-5（20px）热区，迁移后统一到 28px
    const { getByRole } = render(
      <PanelShell
        title="右栏"
        actions={
          <PanelShellAction label="最大化面板">
            <span aria-hidden>⛶</span>
          </PanelShellAction>
        }
      >
        <p>内容</p>
      </PanelShell>,
    );
    const btn = getByRole('button', { name: '最大化面板' });
    expect(btn.className).toContain('h-7');
    expect(btn.className).toContain('min-w-7');
    expect(btn).toHaveAttribute('title', '最大化面板');
  });
});
