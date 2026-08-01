/**
 * SessionTreeView 测试(A24)
 * - 空树渲染占位提示
 * - 递归渲染全部节点,分叉点显示分支数
 * - 点击节点 / Enter 键触发 onSwitchBranch
 * - 当前节点 aria-selected 高亮
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SessionTreeView, type SessionTreeNodeData } from '../SessionTreeView';

/**
 * 构造测试树:root → a → b,且 a → c(a 处分叉)
 */
function buildTree(): Record<string, SessionTreeNodeData> {
  return {
    root: { id: 'root', parentId: null, messageId: 'msg-root', children: ['a'] },
    a: { id: 'a', parentId: 'root', messageId: 'msg-a', children: ['b', 'c'] },
    b: { id: 'b', parentId: 'a', messageId: 'msg-b', children: [] },
    c: { id: 'c', parentId: 'a', messageId: 'msg-c', children: [] },
  };
}

function nodeByTestId(nodeId: string): HTMLElement {
  return document.querySelector(`[data-node-id="${nodeId}"]`) as HTMLElement;
}

describe('SessionTreeView', () => {
  it('renders empty placeholder when tree has no root', () => {
    render(
      <SessionTreeView
        nodes={{}}
        rootNodeId={null}
        currentNodeId={null}
        onSwitchBranch={() => undefined}
      />,
    );
    expect(screen.getByTestId('session-tree-empty')).toHaveTextContent('暂无会话分支');
  });

  it('renders all nodes with their message ids', () => {
    render(
      <SessionTreeView
        nodes={buildTree()}
        rootNodeId="root"
        currentNodeId="b"
        onSwitchBranch={() => undefined}
      />,
    );
    expect(screen.getByText('msg-root')).toBeInTheDocument();
    expect(screen.getByText('msg-a')).toBeInTheDocument();
    expect(screen.getByText('msg-b')).toBeInTheDocument();
    expect(screen.getByText('msg-c')).toBeInTheDocument();
  });

  it('shows fork badge only on branching nodes', () => {
    render(
      <SessionTreeView
        nodes={buildTree()}
        rootNodeId="root"
        currentNodeId="b"
        onSwitchBranch={() => undefined}
      />,
    );
    const forks = screen.getAllByTestId('session-tree-fork');
    expect(forks).toHaveLength(1); // 只有 a 有 2 个子
    expect(forks[0]).toHaveTextContent('2');
  });

  it('calls onSwitchBranch with node id on click', () => {
    const onSwitchBranch = vi.fn();
    render(
      <SessionTreeView
        nodes={buildTree()}
        rootNodeId="root"
        currentNodeId="b"
        onSwitchBranch={onSwitchBranch}
      />,
    );
    fireEvent.click(nodeByTestId('c'));
    expect(onSwitchBranch).toHaveBeenCalledWith('c');
  });

  it('calls onSwitchBranch on Enter key', () => {
    const onSwitchBranch = vi.fn();
    render(
      <SessionTreeView
        nodes={buildTree()}
        rootNodeId="root"
        currentNodeId="b"
        onSwitchBranch={onSwitchBranch}
      />,
    );
    fireEvent.keyDown(nodeByTestId('a'), { key: 'Enter' });
    expect(onSwitchBranch).toHaveBeenCalledWith('a');
  });

  it('marks current node with aria-selected', () => {
    render(
      <SessionTreeView
        nodes={buildTree()}
        rootNodeId="root"
        currentNodeId="b"
        onSwitchBranch={() => undefined}
      />,
    );
    expect(nodeByTestId('b')).toHaveAttribute('aria-selected', 'true');
    expect(nodeByTestId('c')).toHaveAttribute('aria-selected', 'false');
  });

  it('tolerates dangling child references without crashing', () => {
    const nodes = buildTree();
    nodes.a.children.push('ghost');
    render(
      <SessionTreeView
        nodes={nodes}
        rootNodeId="root"
        currentNodeId="b"
        onSwitchBranch={() => undefined}
      />,
    );
    // 正常节点仍然渲染
    expect(screen.getByText('msg-b')).toBeInTheDocument();
  });
});
