import { useState } from 'react';

import { memoryApi } from '../../shared/api';
import { Modal } from '../../shared/ui/Modal';

interface NewMemoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Called after a successful save. Parent uses this to refresh the
   *  memory list without a full page reload. */
  onSaved?: () => void;
}

export function NewMemoryModal({ isOpen, onClose, onSaved }: NewMemoryModalProps) {
  const [content, setContent] = useState('');
  const [memoryType, setMemoryType] = useState<'episodic' | 'semantic'>('episodic');
  const [importance, setImportance] = useState(5);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetForm = () => {
    setContent('');
    setMemoryType('episodic');
    setImportance(5);
    setError(null);
  };

  const handleClose = () => {
    if (saving) return; // Don't allow closing mid-save
    resetForm();
    onClose();
  };

  const handleSave = async () => {
    if (!content.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await memoryApi.saveMemory(content.trim(), memoryType, importance);
      resetForm();
      onSaved?.();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="新建记忆">
      <div className="space-y-3">
        <div>
          <label
            htmlFor="new-memory-content"
            className="block text-xs text-text-secondary mb-1"
          >
            内容
          </label>
          <textarea
            id="new-memory-content"
            data-testid="memory-content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
            className="w-full px-3 py-2 border border-border rounded text-sm bg-bg text-text resize-none focus:outline-none focus:border-primary"
            placeholder="输入记忆内容..."
          />
        </div>

        <div>
          <span className="block text-xs text-text-secondary mb-1">类型</span>
          <div className="flex gap-2" role="radiogroup" aria-label="记忆类型">
            <button
              type="button"
              role="radio"
              aria-checked={memoryType === 'episodic'}
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
              type="button"
              role="radio"
              aria-checked={memoryType === 'semantic'}
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
          <label
            htmlFor="new-memory-importance"
            className="block text-xs text-text-secondary mb-1"
          >
            重要性: {importance}/10
          </label>
          <input
            id="new-memory-importance"
            type="range"
            min={1}
            max={10}
            value={importance}
            onChange={(e) => setImportance(Number(e.target.value))}
            className="w-full"
          />
        </div>

        {error && <div className="text-xs text-error">{error}</div>}
      </div>

      <div className="flex justify-end gap-2 pt-4 mt-3 border-t border-border">
        <button
          type="button"
          onClick={handleClose}
          disabled={saving}
          className="px-3 py-1.5 text-xs border border-border rounded text-text-secondary hover:text-text disabled:opacity-50"
        >
          取消
        </button>
        <button
          type="button"
          data-testid="memory-submit"
          onClick={handleSave}
          disabled={!content.trim() || saving}
          className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? '保存中...' : '保存'}
        </button>
      </div>
    </Modal>
  );
}