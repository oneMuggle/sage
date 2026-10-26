/**
 * LearnedPreferences - 已学偏好（P0-2）
 *
 * 进化任务（PreferenceLearningTask）把学到的稳定偏好写进 `preferences` 表的
 * `pref_*` 键，并同步写入 `user_profile`（category=preference）——
 * 后者才是 system prompt 冻结快照真正读的地方。
 *
 * 用户在这里可以：
 * - 看到进化到底学到了什么
 * - 手动纠正某条偏好
 * - 显式刷新画像快照（进化任务写入时故意不 invalidate，保 prefix cache，
 *   所以「什么时候生效」由用户点这个按钮决定）
 */
import React, { useCallback, useEffect, useState } from 'react';

import { invoke } from '../../shared/api/desktopInvoke';

interface LearnedPreference {
  key: string;
  value: string;
  value_type: string | null;
  category: string | null;
  updated_at: number;
}

interface LearnedPreferencesResponse {
  items: LearnedPreference[];
}

interface ProfileRefreshResponse {
  status: string;
  items_count: number;
  snapshot_chars: number;
}

const formatTime = (timestamp: number): string => {
  try {
    return new Date(timestamp * 1000).toLocaleString('zh-CN');
  } catch {
    return String(timestamp);
  }
};

export const LearnedPreferences: React.FC = () => {
  const [items, setItems] = useState<LearnedPreference[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draftValue, setDraftValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [refreshNote, setRefreshNote] = useState<string | null>(null);

  const fetchPreferences = useCallback(async () => {
    setLoading(true);
    try {
      const result = await invoke<LearnedPreferencesResponse>('get_learned_preferences');
      setItems(result.items ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPreferences();
  }, [fetchPreferences]);

  const startEdit = (item: LearnedPreference) => {
    setEditingKey(item.key);
    setDraftValue(item.value ?? '');
    setRefreshNote(null);
  };

  const saveEdit = async (key: string) => {
    setSaving(true);
    try {
      await invoke('update_learned_preference', { key, value: draftValue });
      setEditingKey(null);
      setRefreshNote('偏好已保存。要立即进 prompt 快照，请点「刷新画像快照」。');
      await fetchPreferences();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const refreshSnapshot = async () => {
    setSaving(true);
    try {
      const result = await invoke<ProfileRefreshResponse>('refresh_user_profile');
      setRefreshNote(`画像快照已刷新：${result.items_count} 条，${result.snapshot_chars} 字符。`);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-text">已学偏好</h3>
        <div className="flex items-center gap-3">
          <button
            onClick={refreshSnapshot}
            disabled={saving}
            className="text-sm text-primary hover:text-primary-hover disabled:opacity-50"
          >
            刷新画像快照
          </button>
          <button
            onClick={fetchPreferences}
            className="text-sm text-primary hover:text-primary-hover"
          >
            刷新
          </button>
        </div>
      </div>

      <p className="text-xs text-muted">
        偏好由后台进化任务自动学习。进化任务写入画像时不会重建冻结快照（保 prefix
        cache），因此改动需手动点「刷新画像快照」才会立刻进入下一轮对话。
      </p>

      {refreshNote && (
        <p role="status" className="text-xs text-success">
          {refreshNote}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-error">
          {error}
        </p>
      )}

      {loading ? (
        <div className="text-muted text-sm">加载中...</div>
      ) : items.length === 0 ? (
        <div className="text-center py-6 text-muted text-sm">
          暂无已学偏好 —— 后台偏好学习任务执行后会自动出现在这里。
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li
              key={item.key}
              className="bg-surface rounded-lg shadow-sm p-3 border border-border text-sm"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-muted font-mono">{item.key}</div>
                  {editingKey === item.key ? (
                    <input
                      value={draftValue}
                      onChange={(e) => setDraftValue(e.target.value)}
                      className="mt-1 w-full bg-bg-subtle rounded px-2 py-1 text-sm text-text"
                      aria-label={`编辑 ${item.key}`}
                    />
                  ) : (
                    <div className="mt-1 text-text break-words">{item.value}</div>
                  )}
                  <div className="mt-1 text-xs text-muted">
                    更新于 {formatTime(item.updated_at)}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {editingKey === item.key ? (
                    <>
                      <button
                        onClick={() => saveEdit(item.key)}
                        disabled={saving || !draftValue.trim()}
                        className="text-xs text-primary hover:text-primary-hover disabled:opacity-50"
                      >
                        保存
                      </button>
                      <button
                        onClick={() => setEditingKey(null)}
                        className="text-xs text-text-secondary hover:text-text"
                      >
                        取消
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => startEdit(item)}
                      className="text-xs text-primary hover:text-primary-hover"
                    >
                      纠正
                    </button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default LearnedPreferences;
