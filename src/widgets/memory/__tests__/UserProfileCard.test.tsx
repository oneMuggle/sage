// src/widgets/memory/__tests__/UserProfileCard.test.tsx
// 对标 S2: "关于我" 可编辑画像卡片 —— memoryApi 全 mock。
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserProfileEntry, UserProfileResponse } from '../../../shared/api/types';
import { UserProfileCard } from '../UserProfileCard';

const getUserProfile = vi.fn<() => Promise<UserProfileResponse>>();
const createUserProfile =
  vi.fn<(c: string, cat?: string, imp?: number) => Promise<UserProfileEntry | null>>();
const updateUserProfile =
  vi.fn<(id: string, p: Record<string, unknown>) => Promise<UserProfileEntry | null>>();
const deleteUserProfile = vi.fn<(id: string) => Promise<void>>();

vi.mock('../../../shared/api', () => ({
  memoryApi: {
    getUserProfile: () => getUserProfile(),
    createUserProfile: (...a: [string, string?, number?]) => createUserProfile(...a),
    updateUserProfile: (...a: [string, Record<string, unknown>]) => updateUserProfile(...a),
    deleteUserProfile: (id: string) => deleteUserProfile(id),
  },
}));

function entry(overrides: Partial<UserProfileEntry>): UserProfileEntry {
  return {
    id: 'p1',
    content: '用户偏好简洁回答',
    category: 'preference',
    importance: 7,
    source: 'auto',
    created_at: 1,
    updated_at: 1,
    ...overrides,
  };
}

function profile(items: UserProfileEntry[]): UserProfileResponse {
  return {
    items,
    categories: ['preference', 'communication_style', 'workflow_habit', 'identity'],
    snapshot: '',
    char_limit: 800,
  };
}

describe('UserProfileCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    deleteUserProfile.mockResolvedValue(undefined);
  });

  it('空画像显示引导文案', async () => {
    getUserProfile.mockResolvedValue(profile([]));
    render(<UserProfileCard />);
    await waitFor(() => expect(screen.getByTestId('profile-empty')).toBeInTheDocument());
  });

  it('渲染条目并显示类别中文标签', async () => {
    getUserProfile.mockResolvedValue(
      profile([
        entry({}),
        entry({ id: 'p2', content: '后端工程师', category: 'identity', importance: 4 }),
      ]),
    );
    render(<UserProfileCard />);
    await waitFor(() => expect(screen.getAllByTestId('profile-item')).toHaveLength(2));
    expect(screen.getByText('偏好')).toBeInTheDocument();
    expect(screen.getByText('身份背景')).toBeInTheDocument();
    expect(screen.getByText('★7')).toBeInTheDocument();
  });

  it('新增条目后重新加载列表', async () => {
    getUserProfile
      .mockResolvedValueOnce(profile([]))
      .mockResolvedValueOnce(profile([entry({ content: '常用 Python' })]));
    createUserProfile.mockResolvedValue(entry({ content: '常用 Python' }));
    render(<UserProfileCard />);
    await waitFor(() => expect(screen.getByTestId('profile-empty')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('profile-add'));
    fireEvent.change(screen.getByTestId('profile-editor-content'), {
      target: { value: '常用 Python' },
    });
    fireEvent.change(screen.getByTestId('profile-editor-category'), {
      target: { value: 'workflow_habit' },
    });
    fireEvent.click(screen.getByTestId('profile-editor-submit'));

    await waitFor(() =>
      expect(createUserProfile).toHaveBeenCalledWith('常用 Python', 'workflow_habit', 5),
    );
    await waitFor(() => expect(screen.getByText('常用 Python')).toBeInTheDocument());
    expect(screen.queryByTestId('profile-editor')).toBeNull();
  });

  it('后端拒绝（重复）时显示错误并保留编辑器', async () => {
    getUserProfile.mockResolvedValue(profile([]));
    createUserProfile.mockResolvedValue(null);
    render(<UserProfileCard />);
    await waitFor(() => expect(screen.getByTestId('profile-empty')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('profile-add'));
    fireEvent.change(screen.getByTestId('profile-editor-content'), { target: { value: '重复' } });
    fireEvent.click(screen.getByTestId('profile-editor-submit'));
    await waitFor(() => expect(screen.getByTestId('profile-error')).toBeInTheDocument());
    expect(screen.getByTestId('profile-editor')).toBeInTheDocument();
  });

  it('编辑条目走 updateUserProfile', async () => {
    getUserProfile.mockResolvedValue(profile([entry({})]));
    updateUserProfile.mockResolvedValue(entry({ content: '偏好详细回答' }));
    render(<UserProfileCard />);
    await waitFor(() => expect(screen.getByTestId('profile-item')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('profile-edit'));
    const ta = screen.getByTestId('profile-editor-content') as HTMLTextAreaElement;
    expect(ta.value).toBe('用户偏好简洁回答');
    fireEvent.change(ta, { target: { value: '偏好详细回答' } });
    fireEvent.click(screen.getByTestId('profile-editor-submit'));
    await waitFor(() =>
      expect(updateUserProfile).toHaveBeenCalledWith('p1', {
        content: '偏好详细回答',
        category: 'preference',
        importance: 7,
      }),
    );
  });

  it('删除条目走 deleteUserProfile 并刷新', async () => {
    getUserProfile.mockResolvedValueOnce(profile([entry({})])).mockResolvedValueOnce(profile([]));
    render(<UserProfileCard />);
    await waitFor(() => expect(screen.getByTestId('profile-item')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('profile-delete'));
    await waitFor(() => expect(deleteUserProfile).toHaveBeenCalledWith('p1'));
    await waitFor(() => expect(screen.getByTestId('profile-empty')).toBeInTheDocument());
  });
});
