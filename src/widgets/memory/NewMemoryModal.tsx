import { X } from 'lucide-react';
import { useState } from 'react';

import { memoryApi } from '../../lib/api';

interface NewMemoryModalProps {
  onClose: () => void;
}

export function NewMemoryModal({ onClose }: NewMemoryModalProps) {
  const [content, setContent] = useState('');
  const [memoryType, setMemoryType] = useState<'episodic' | 'semantic'>('episodic');
  const [importance, setImportance] = useState(5);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!content.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await memoryApi.saveMemory(content.trim(), memoryType, importance);
      onClose();
      // Reload the page to show new memory
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-surface border border-border rounded-lg w-full max-w-md mx-4 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-text">新建记忆</h3>
          <button onClick={onClose} className="p-1 hover:bg-bg-hover rounded">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-xs text-text-secondary mb-1">内容</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              className="w-full px-3 py-2 border border-border rounded text-sm bg-bg text-text resize-none focus:outline-none focus:border-primary"
              placeholder="输入记忆内容..."
            />
          </div>

          <div>
            <label className="block text-xs text-text-secondary mb-1">类型</label>
            <div className="flex gap-2">
              <button
                onClick={() => setMemoryType('episodic')}
                className={`px-3 py-1 text-xs rounded border ${
                  memoryType === 'episodic'
                    ? 'bg-primary/10 text-primary border-primary'
                    : 'border-border text-text-secondary'
                }`}
              >
                情景记忆
              </button>
              <button
                onClick={() => setMemoryType('semantic')}
                className={`px-3 py-1 text-xs rounded border ${
                  memoryType === 'semantic'
                    ? 'bg-primary/10 text-primary border-primary'
                    : 'border-border text-text-secondary'
                }`}
              >
                语义记忆
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs text-text-secondary mb-1">
              重要性: {importance}/10
            </label>
            <input
              type="range"
              min={1}
              max={10}
              value={importance}
              onChange={(e) => setImportance(Number(e.target.value))}
              className="w-full"
            />
          </div>

          {error && <div className="text-xs text-error">{error}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs border border-border rounded text-text-secondary hover:text-text"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={!content.trim() || saving}
              className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
