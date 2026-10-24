import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ProjectPicker } from '../ProjectPicker';

const mockProjects = [
  { id: 'proj-1', name: 'Project Alpha', path: '/path/to/alpha', sessionId: null },
  { id: 'proj-2', name: 'Project Beta', path: '/path/to/beta', sessionId: 'session-1' },
  { id: 'proj-3', name: 'Test Project', path: '/path/to/test', sessionId: null },
];

describe('ProjectPicker', () => {
  it('renders with placeholder when no value', () => {
    render(<ProjectPicker value={null} onChange={vi.fn()} projects={mockProjects} />);
    expect(screen.getByText('选择项目')).toBeInTheDocument();
  });

  it('renders selected project name', () => {
    render(<ProjectPicker value="proj-1" onChange={vi.fn()} projects={mockProjects} />);
    expect(screen.getByText('Project Alpha')).toBeInTheDocument();
  });

  it('shows "不绑定项目" option', () => {
    render(<ProjectPicker value={null} onChange={vi.fn()} projects={mockProjects} />);
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('不绑定项目')).toBeInTheDocument();
  });

  it('calls onChange when selecting a project', () => {
    const onChange = vi.fn();
    render(<ProjectPicker value={null} onChange={onChange} projects={mockProjects} />);
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.click(screen.getByText('Project Beta'));
    expect(onChange).toHaveBeenCalledWith('proj-2');
  });

  it('calls onChange with null when selecting "不绑定项目"', () => {
    const onChange = vi.fn();
    render(<ProjectPicker value="proj-1" onChange={onChange} projects={mockProjects} />);
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.click(screen.getByText('不绑定项目'));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('filters projects by search query', () => {
    render(<ProjectPicker value={null} onChange={vi.fn()} projects={mockProjects} />);
    fireEvent.click(screen.getByRole('combobox'));
    const searchInput = screen.getByPlaceholderText('搜索项目...');
    fireEvent.change(searchInput, { target: { value: 'test' } });
    expect(screen.getByText('Test Project')).toBeInTheDocument();
    expect(screen.queryByText('Project Alpha')).not.toBeInTheDocument();
    expect(screen.queryByText('Project Beta')).not.toBeInTheDocument();
  });

  it('shows empty state when no projects match search', () => {
    render(<ProjectPicker value={null} onChange={vi.fn()} projects={mockProjects} />);
    fireEvent.click(screen.getByRole('combobox'));
    const searchInput = screen.getByPlaceholderText('搜索项目...');
    fireEvent.change(searchInput, { target: { value: 'nonexistent' } });
    expect(screen.getByText('未找到匹配的项目')).toBeInTheDocument();
  });

  it('shows empty state when no projects available', () => {
    render(<ProjectPicker value={null} onChange={vi.fn()} projects={[]} />);
    fireEvent.click(screen.getByRole('combobox'));
    expect(screen.getByText('暂无可用项目')).toBeInTheDocument();
  });
});
