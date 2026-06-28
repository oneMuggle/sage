/**
 * CSS 主题编辑模态框
 *
 * 功能：
 * - 集成 CodeMirrorThemeEditor
 * - 主题名称输入框（1-32 字符）
 * - 封面图上传（可选，data URL，限制 2MB）
 * - 实时预览（调用 backgroundInjector.injectPreviewCss）
 * - 保存按钮（调用 themeCssClient.save）
 * - 删除按钮（编辑模式，调用 themeCssClient.delete）
 * - 取消按钮
 */

import { Dialog, Transition } from '@headlessui/react';
import { Fragment, useEffect, useMemo, useState } from 'react';

import { themeCssClient } from '../../shared/api/themeCssClient';

import { CodeMirrorThemeEditor } from './CodeMirrorThemeEditor';
import { injectPreviewCss } from './backgroundInjector';
import type { ThemeCssPayload } from './themeCssTypes';
import { themeCssValidator } from './themeCssValidator';

interface CssThemeModalProps {
  open: boolean;
  onClose: () => void;
  initialTheme?: ThemeCssPayload; // 编辑模式
  onSaved: () => void;
}

const DEFAULT_CSS = `:root {
  --bg-base: #ffffff;
  --bg-1: #f5f5f5;
  --text-primary: #111827;
  --primary: #4f46e5;
  --border-base: #e5e7eb;
}`;

const MAX_COVER_SIZE = 2 * 1024 * 1024; // 2MB
const ALLOWED_COVER_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

function uuid(): string {
  return crypto.randomUUID();
}

export function CssThemeModal({ open, onClose, initialTheme, onSaved }: CssThemeModalProps) {
  const isEditMode = !!initialTheme;

  const [name, setName] = useState(initialTheme?.name ?? '');
  const [css, setCss] = useState(initialTheme?.css ?? DEFAULT_CSS);
  const [cover, setCover] = useState<string | undefined>(initialTheme?.cover);
  const [appearance] = useState<'light' | 'dark'>(initialTheme?.appearance ?? 'light');
  const [coverError, setCoverError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // 实时校验
  const validation = useMemo(() => themeCssValidator.validate(css), [css]);

  // 可保存条件：名称非空 + 校验通过 + 无封面错误
  const canSave = name.length > 0 && name.length <= 32 && validation.ok && !coverError;

  // 实时预览注入
  useEffect(() => {
    if (validation.ok) {
      injectPreviewCss(css);
    }
  }, [css, validation.ok]);

  // 打开时初始化状态
  useEffect(() => {
    if (open) {
      setName(initialTheme?.name ?? '');
      setCss(initialTheme?.css ?? DEFAULT_CSS);
      setCover(initialTheme?.cover);
      setCoverError(null);
      setSaving(false);
    }
  }, [open, initialTheme]);

  async function handleCoverChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) {
      setCover(undefined);
      return;
    }
    if (!ALLOWED_COVER_TYPES.includes(file.type)) {
      setCoverError('封面图必须是 PNG / JPEG / WebP / GIF 格式');
      return;
    }
    if (file.size > MAX_COVER_SIZE) {
      setCoverError(`封面图大小 ${(file.size / 1024 / 1024).toFixed(1)}MB 超过限制 2MB`);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setCover(reader.result as string);
      setCoverError(null);
    };
    reader.readAsDataURL(file);
  }

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    try {
      const now = Date.now();
      const payload: ThemeCssPayload = {
        id: initialTheme?.id ?? uuid(),
        name,
        cover,
        css,
        appearance,
        created_at: initialTheme?.created_at ?? now,
        updated_at: now,
      };
      await themeCssClient.save(payload);
      onSaved();
      onClose();
    } catch (error) {
      console.error('[CssThemeModal] save failed:', error);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!initialTheme?.id) return;
    if (!window.confirm(`确认删除主题 "${name}"？`)) return;
    try {
      await themeCssClient.delete(initialTheme.id);
      onClose();
    } catch (error) {
      console.error('[CssThemeModal] delete failed:', error);
    }
  }

  if (!open) return null;

  return (
    <Transition appear show={open} as={Fragment}>
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

        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-200"
              enterFrom="opacity-0 scale-95"
              enterTo="opacity-100 scale-100"
              leave="ease-in duration-150"
              leaveFrom="opacity-100 scale-100"
              leaveTo="opacity-0 scale-95"
            >
              <Dialog.Panel className="w-full max-w-3xl transform overflow-hidden rounded-xl bg-surface-elevated dark:bg-surface shadow-xl transition-all">
                {/* 头部 */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-border">
                  <Dialog.Title as="h3" className="text-lg font-semibold">
                    {isEditMode ? `编辑主题：${name}` : '新建自定义主题'}
                  </Dialog.Title>
                </div>

                {/* 内容 */}
                <div className="px-6 py-4 space-y-4 max-h-[70vh] overflow-y-auto">
                  {/* 名称 */}
                  <div>
                    <label htmlFor="theme-name" className="block text-sm font-medium mb-1">
                      主题名称
                    </label>
                    <input
                      id="theme-name"
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      maxLength={32}
                      className="w-full px-3 py-2 border border-border rounded-radius-md bg-bg-base"
                    />
                    {name.length > 32 && (
                      <p className="text-xs text-error mt-1">名称最多 32 字符</p>
                    )}
                  </div>

                  {/* 封面图 */}
                  <div>
                    <label htmlFor="theme-cover" className="block text-sm font-medium mb-1">
                      封面图（可选，≤ 2MB）
                    </label>
                    <input
                      id="theme-cover"
                      type="file"
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      onChange={handleCoverChange}
                      className="block w-full text-sm"
                    />
                    {cover && !coverError && (
                      <img
                        src={cover}
                        alt="cover"
                        className="mt-2 w-32 h-20 object-cover rounded"
                      />
                    )}
                    {coverError && <p className="text-xs text-error mt-1">{coverError}</p>}
                  </div>

                  {/* CSS 编辑器 */}
                  <div>
                    <label className="block text-sm font-medium mb-1">
                      CSS（仅允许 16 个白名单变量）
                    </label>
                    <CodeMirrorThemeEditor
                      value={css}
                      onChange={setCss}
                      error={!validation.ok ? validation.error : undefined}
                    />
                    {!validation.ok && validation.error && (
                      <p className="mt-2 text-xs text-error">{validation.error}</p>
                    )}
                  </div>
                </div>

                {/* 底部 */}
                <div className="px-6 py-4 border-t border-border flex justify-between">
                  <div>
                    {isEditMode && (
                      <button
                        type="button"
                        onClick={handleDelete}
                        className="px-4 py-2 text-sm text-error hover:bg-error/10 rounded-radius-md"
                      >
                        删除
                      </button>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={onClose}
                      className="px-4 py-2 text-sm border border-border rounded-radius-md hover:bg-bg-hover"
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      onClick={handleSave}
                      disabled={!canSave || saving}
                      className="px-4 py-2 text-sm bg-primary text-white rounded-radius-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-primary-hover"
                    >
                      {saving ? '保存中…' : '保存'}
                    </button>
                  </div>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}
