/**
 * TM3 (DSH 对标 ZCode): 键盘快捷键帮助面板。
 *
 * Ctrl+/ (或 F1) 唤出，展示 sage 聊天界面所有可用快捷键。
 * 参考 deepseek-harness Web UI 的 ControlHintTooltip kbd 样式模式。
 */
import { useEffect, useState } from 'react';

import { useStore } from '../../shared/lib/store';

interface ShortcutEntry {
  keys: string;
  description: string;
}

const SHORTCUTS: ShortcutEntry[] = [
  { keys: 'Enter', description: '发送消息' },
  { keys: 'Shift+Enter', description: '换行' },
  { keys: 'Escape', description: '中断生成 / 关闭面板' },
  { keys: 'Ctrl+/', description: '快捷键帮助' },
  { keys: 'Ctrl+N', description: '新建会话' },
  { keys: 'Ctrl+Shift+F', description: '搜索会话' },
];

const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);
const modKey = isMac ? '⌘' : 'Ctrl';

function formatKeys(keys: string): string {
  return keys.replace('Ctrl+', `${modKey}+`);
}

export function KeyboardShortcutsHelp() {
  const [open, setOpen] = useState(false);
  const currentSessionId = useStore((s) => s.currentSessionId);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === 'Escape' && open) {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open]);

  if (!open || !currentSessionId) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      data-testid="keyboard-shortcuts-overlay"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-80 max-w-[90vw] rounded-lg border border-slate-200 bg-white p-4 shadow-lg dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-200">
          键盘快捷键
        </h3>
        <ul className="space-y-2">
          {SHORTCUTS.map((s) => (
            <li key={s.keys} className="flex items-center justify-between text-xs">
              <span className="text-slate-600 dark:text-slate-400">{s.description}</span>
              <kbd className="rounded border border-slate-300 px-1.5 py-0.5 font-mono text-ui-2xs text-slate-500 dark:border-slate-600 dark:text-slate-400">
                {formatKeys(s.keys)}
              </kbd>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-ui-xs text-slate-400">
          按 Esc 关闭
        </p>
      </div>
    </div>
  );
}
