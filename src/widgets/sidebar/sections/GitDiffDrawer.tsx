/**
 * GitDiffDrawer — 全屏 diff 视图覆盖层。
 *
 * 点击侧边栏 git 文件行时打开，展示该文件相对于 HEAD 的 unified diff。
 * 使用 Headless UI Dialog 原语实现，宽度 90vw、高度 85vh。
 * diff 渲染复用 chat/changes/SplitDiff 组件（side-by-side + 词级高亮）。
 */

import { Dialog, Transition } from '@headlessui/react';
import { X } from 'lucide-react';
import { Fragment, useEffect, useState } from 'react';

import { getGitDiff, type GitDiffResponse } from '../../../shared/api/gitStatusApi';
import { useI18n } from '../../../shared/lib/i18n';
import { SplitDiff } from '../../chat/changes/SplitDiff';

interface GitDiffDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  projectPath: string;
  filePath: string;
  fileStatus: string;
}

export function GitDiffDrawer({
  isOpen,
  onClose,
  projectPath,
  filePath,
  fileStatus,
}: GitDiffDrawerProps) {
  const { t } = useI18n();
  const [diff, setDiff] = useState<GitDiffResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !projectPath || !filePath) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDiff(null);

    getGitDiff(projectPath, filePath)
      .then((result) => {
        if (!cancelled) setDiff(result);
      })
      .catch(() => {
        if (!cancelled) setError(t('git.diff_load_error'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isOpen, projectPath, filePath, t]);

  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-overlay" />
        </Transition.Child>

        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Transition.Child
            as={Fragment}
            enter="ease-out duration-200"
            enterFrom="opacity-0 scale-95"
            enterTo="opacity-100 scale-100"
            leave="ease-in duration-150"
            leaveFrom="opacity-100 scale-100"
            leaveTo="opacity-0 scale-95"
          >
            <Dialog.Panel className="flex w-[90vw] max-w-5xl h-[85vh] flex-col overflow-hidden rounded-xl bg-surface-elevated dark:bg-surface shadow-xl">
              {/* Header */}
              <div className="flex items-center justify-between border-b border-border px-4 py-3">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-ui-xs font-mono text-text-muted shrink-0">
                    {fileStatus}
                  </span>
                  <Dialog.Title as="h3" className="text-ui-sm font-semibold truncate">
                    {filePath}
                  </Dialog.Title>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  className="shrink-0 rounded-lg p-1 text-text-muted hover:text-text hover:bg-bg-hover"
                  aria-label={t('git.close')}
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Content */}
              <div className="flex-1 overflow-auto">
                {loading && (
                  <p className="text-ui-xs text-text-muted px-4 py-8 text-center italic">
                    {t('git.diff_loading')}
                  </p>
                )}
                {error && <p className="text-ui-xs text-error px-4 py-8 text-center">{error}</p>}
                {diff && !diff.diff_text && (
                  <p className="text-ui-xs text-text-muted px-4 py-8 text-center italic">
                    {diff.is_new_file
                      ? t('git.diff_empty_new')
                      : diff.is_deleted
                        ? t('git.diff_empty_deleted')
                        : t('git.diff_no_changes')}
                  </p>
                )}
                {diff && diff.diff_text && <SplitDiff diff={diff.diff_text} />}
              </div>
            </Dialog.Panel>
          </Transition.Child>
        </div>
      </Dialog>
    </Transition>
  );
}
