import { useCallback, useEffect, useState } from 'react';

import { useAtFileMenu } from '../../features/chat/useAtFileMenu';
import type { PendingComposerOptions } from '../../features/send-message/pendingComposerOptions';
import { useTypewriterPlaceholder } from '../../features/welcome/useTypewriterPlaceholder';
import type { ChatOfficeRef } from '../../shared/api/types';
import { useFileUpload } from '../../shared/lib/hooks/useFileUpload';
import { useOptionalWorkspaceContext } from '../../shared/lib/workspaceContext';
import { InputCard } from '../chat/InputCard';

interface WelcomeInputCardProps {
  placeholder?: string;
  typewriterPhrases?: string[];
  onSend?: (value: string, options?: PendingComposerOptions) => void;
  disabled?: boolean;
  initialValue?: string;
  toolbar?: React.ReactNode;
  /**
   * `@` 查询激活时触发 —— 新会话页借此懒创建草稿会话，使文件搜索能拿到
   * 会话绑定的工作区（AtFileMenu 依赖 sessionId 查询后端）。
   */
  onAtQueryActive?: () => void;
  /**
   * 外部回填的草稿（例如用户点击首屏 prompt chip）。
   * 传入新的对象实例即视为一次新的回填请求 —— 同一个 chip 连点两次也会重新填充。
   */
  draft?: { text: string } | null;
}

export function formatWelcomeInputMarkdown(params: {
  value: string;
  placeholder: string;
  disabled: boolean;
}): string {
  return [
    '# 欢迎页输入卡片草稿 (Welcome Input Draft)',
    '',
    `- **当前占位文案**: ${params.placeholder || '无'}`,
    `- **禁用状态**: ${params.disabled ? '已禁用' : '可输入'}`,
    `- **草稿字符数**: ${params.value.length}`,
    '',
    '## 草稿正文',
    '',
    params.value || '_空_',
  ].join('\n');
}

export function formatWelcomeInputJson(params: {
  value: string;
  placeholder: string;
  disabled: boolean;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      ...params,
    },
    null,
    2,
  );
}

export function WelcomeInputCard({
  placeholder,
  typewriterPhrases,
  onSend,
  disabled = false,
  initialValue = '',
  toolbar,
  onAtQueryActive,
  draft = null,
}: WelcomeInputCardProps) {
  const [value, setValue] = useState(initialValue);
  const [cursorPos, setCursorPos] = useState(initialValue.length);
  const [officeRefs, setOfficeRefs] = useState<readonly ChatOfficeRef[]>([]);
  const [focusSeq, setFocusSeq] = useState(0);

  const {
    files,
    images,
    addFile,
    addImage,
    removeFile,
    removeImage,
    clearAll,
    handleDrop,
    handleDragOver,
    handlePaste,
    isDragOver,
  } = useFileUpload();

  // 新会话页提交前没有会话；草稿会话创建后 provider 会回填 binding，
  // office 导入即可用。文件搜索本身由 AtFileMenu 通过 sessionId 完成。
  const workspaceContext = useOptionalWorkspaceContext();
  const workspacePath = workspaceContext?.binding?.workspacePath;

  // 2026-10-29: 用 useCallback 稳定引用, 避免每次渲染重建导致 useAtFileMenu 的
  // handleAtFileSelect 闭包失效、AtFileMenu 被迫重新渲染。
  const addOfficeRef = useCallback((ref: ChatOfficeRef) => {
    setOfficeRefs((prev) => (prev.some((r) => r.docId === ref.docId) ? prev : [...prev, ref]));
  }, []);
  const removeOfficeRef = useCallback((docId: string) => {
    setOfficeRefs((prev) => prev.filter((r) => r.docId !== docId));
  }, []);

  const { atFileMenu } = useAtFileMenu({
    value,
    cursorPos,
    onChange: setValue,
    onCursorChange: setCursorPos,
    workspacePath,
    addOfficeRef,
    onQueryActive: onAtQueryActive,
  });

  const { current: typewriterText } = useTypewriterPlaceholder(typewriterPhrases ?? ['']);

  useEffect(() => {
    setValue(initialValue);
    setCursorPos(initialValue.length);
  }, [initialValue]);

  // 外部草稿回填：以对象引用变化作为触发信号，同一个 chip 连点两次也会重新填充。
  // 先写值再让 InputCard 聚焦（focusRequest 变化），保证光标落在新文本末尾。
  useEffect(() => {
    if (!draft) return;
    setValue(draft.text);
    setCursorPos(draft.text.length);
    setFocusSeq((seq) => seq + 1);
  }, [draft]);

  const handleChange = (newValue: string) => {
    setValue(newValue);
    setCursorPos(newValue.length);
  };

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files;
    if (!selectedFiles) return;
    Array.from(selectedFiles).forEach(addImage);
    e.target.value = '';
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files;
    if (!selectedFiles) return;
    Array.from(selectedFiles).forEach(addFile);
    e.target.value = '';
  };

  const hasAttachments =
    files.length > 0 || images.length > 0 || officeRefs.length > 0 || value.trim().length > 0;

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!hasAttachments || !onSend) return;
    const options: PendingComposerOptions | undefined =
      files.length > 0 || images.length > 0 || officeRefs.length > 0
        ? {
            attachments: files.length > 0 ? files : undefined,
            images: images.length > 0 ? images : undefined,
            officeRefs: officeRefs.length > 0 ? officeRefs : undefined,
          }
        : undefined;
    onSend(trimmed, options);
    setValue('');
    setCursorPos(0);
    setOfficeRefs([]);
    clearAll();
  };

  const effectivePlaceholder =
    typewriterPhrases && typewriterPhrases.length > 0 ? typewriterText : (placeholder ?? '');

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <div className="w-full max-w-2xl mx-auto" data-testid="welcome-input-card">
      <div className="focus-within:shadow-[0_0_0_3px_var(--primary-focus-ring)] transition-shadow">
        <InputCard
          value={value}
          onChange={handleChange}
          onSubmit={handleSubmit}
          placeholder={effectivePlaceholder}
          disabled={disabled}
          files={files}
          images={images}
          officeRefs={officeRefs}
          onRemoveFile={removeFile}
          onRemoveImage={removeImage}
          onRemoveOfficeRef={removeOfficeRef}
          onImageSelect={handleImageSelect}
          onFileSelect={handleFileSelect}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onPaste={handlePaste}
          isDragOver={isDragOver}
          atFileMenu={atFileMenu}
          enableCommandItem={false}
          autoFocus
          focusRequest={focusSeq}
        />
      </div>
      {toolbar && <div className="mt-1">{toolbar}</div>}
    </div>
  );
}
