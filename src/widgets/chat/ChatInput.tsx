import { useCallback, useEffect, useState } from 'react';

import { AtFileMenu, useAtFileQuery, useBtwCommand } from '../../features/chat';
import { importOfficeReference } from '../../features/office/importOfficeReference';
import { skillsApi } from '../../shared/api';
import { type AtFileSelection } from '../../shared/api/fileSearchClient';
import type { ChatOfficeRef } from '../../shared/api/types';
import { useFileUpload } from '../../shared/lib/hooks/useFileUpload';
import { useI18n } from '../../shared/lib/i18n';
import { useOptionalWorkspaceContext } from '../../shared/lib/workspaceContext';

import { InputCard, type KnowledgeDocType } from './InputCard';
import {
  commandToPrompt,
  mergeSlashCommands,
  type DynamicSlashSkill,
  type SlashCommand,
} from './slashCommands';

interface ChatInputProps {
  onSend: (
    message: string,
    options?: {
      knowledgeRefs?: { id: string; title: string }[];
      attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
      images?: { name: string; size: number; type: string; dataUrl?: string }[];
      /**
       * Task 7 (2026-07-26): managed Office references from the @-menu.
       * The Chat page forwards these into `chatApi.chatStream`'s 5th arg
       * so the LLM can see the office doc summaries.
       */
      officeRefs?: readonly ChatOfficeRef[];
    },
  ) => void;
  onInterrupt?: () => void;
  onClear?: () => void;
  /**
   * M4: /compact slash action 回调。由 Chat 页面实现（调用 session_compact
   * IPC + toast + 重载消息）。未提供时 /compact 静默无操作。
   */
  onCompact?: () => void;
  isLoading?: boolean;
  disabled?: boolean;
  placeholder?: string;
  /**
   * Optional workspace root — kept for backwards-compat with callers that
   * haven't migrated to the SessionWorkspaceProvider yet. When the
   * provider is mounted (Chat page via SessionWorkspaceProvider), the
   * menu reads sessionId + workspacePath from there instead.
   */
  workspacePath?: string;
}

const KNOWLEDGE_DOCS: KnowledgeDocType[] = [
  { id: 'prd', title: '产品需求文档', desc: 'Sage 核心功能定义' },
  { id: 'api-docs', title: 'API 接口文档', desc: '内部 API 网关说明' },
  { id: 'deploy-guide', title: '部署指南', desc: 'Windows 环境部署步骤' },
  { id: 'memory-arch', title: '记忆系统架构', desc: '本地存储与同步策略' },
  { id: 'ui-spec', title: 'UI 设计规范', desc: '设计令牌与组件库' },
  { id: 'test-data', title: '测试数据集', desc: '样本对话和测试用例' },
];

export function ChatInput({
  onSend,
  onInterrupt,
  onClear,
  onCompact,
  isLoading = false,
  disabled = false,
  placeholder,
  workspacePath,
}: ChatInputProps) {
  const { t } = useI18n();
  const [value, setValue] = useState('');
  const [cursorPos, setCursorPos] = useState(0);
  const [knowledgeRefs, setKnowledgeRefs] = useState<{ id: string; title: string }[]>([]);
  const [showKnowledgeSelector, setShowKnowledgeSelector] = useState(false);
  const [slashMenuOpen, setSlashMenuOpen] = useState(false);
  const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
  const [slashSelectedIndex, setSlashSelectedIndex] = useState(0);
  // Path B: dynamic SKILL.md slash command names fetched from the backend.
  // On fetch failure we silently fall back to an empty list (no slash skills).
  const [dynamicSlashCommands, setDynamicSlashCommands] = useState<DynamicSlashSkill[]>([]);

  // Task 7 (2026-07-26): managed Office refs attached via the @ menu.
  // Dedupe by docId (immutable state — every update is a new array).
  const [officeRefs, setOfficeRefs] = useState<readonly ChatOfficeRef[]>([]);

  // Workspace context — provides sessionId + binding for the @ menu.
  // Falls back to the legacy `workspacePath` prop for callers that don't
  // mount the provider (e.g. some legacy tests). Use the optional variant
  // so legacy tests that don't mount the provider don't throw.
  const workspaceContext = useOptionalWorkspaceContext();
  const effectiveWorkspacePath = workspaceContext?.binding?.workspacePath ?? workspacePath;
  // sessionId is used by the AtFileMenu itself (via useOptionalWorkspaceContext);
  // expose on the closure so future tests can assert on it.
  const effectiveSessionId = workspaceContext?.sessionId ?? null;

  // Phase 6: @文件提及 + /btw 补充消息
  const btw = useBtwCommand();
  const atQuery = useAtFileQuery(value, cursorPos);

  // Fetch SKILL.md skills on mount. Filter to user-invocable ones for slash menu.
  // The full `description` from the SKILL.md frontmatter is passed through so the
  // menu can display meaningful descriptions (not just "Skill: <name>").
  // List is loaded once; re-mount or restart app to pick up new SKILL.md.
  useEffect(() => {
    skillsApi
      .list()
      .then((skills) => {
        const dynamic = skills
          .filter((s) => s.dispatch?.user_invocable === true)
          .map((s) => ({
            commandName: s.dispatch?.user_invocable_name ?? `/${s.name}`,
            description: s.description,
          }));
        setDynamicSlashCommands(dynamic);
      })
      .catch(() => setDynamicSlashCommands([]));
  }, []);

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
    isDragOver,
  } = useFileUpload();

  /**
   * Insert a plain `@<path> ` into the textarea, replacing the @-query.
   */
  const insertAtFilePath = useCallback(
    (filePath: string) => {
      if (atQuery.query === null) return;
      const newValue =
        value.slice(0, atQuery.startIdx) + '@' + filePath + ' ' + value.slice(atQuery.endIdx);
      setValue(newValue);
      setCursorPos(atQuery.startIdx + 1 + filePath.length + 1);
    },
    [value, atQuery],
  );

  /**
   * Add a managed office ref. Dedupe by `docId` — adding the same docId
   * twice is a no-op (immutable update).
   */
  const addOfficeRef = useCallback((ref: ChatOfficeRef) => {
    setOfficeRefs((prev) => {
      if (prev.some((r) => r.docId === ref.docId)) return prev;
      return [...prev, ref];
    });
  }, []);

  /**
   * Remove an office ref by docId.
   */
  const removeOfficeRef = useCallback((docId: string) => {
    setOfficeRefs((prev) => prev.filter((r) => r.docId !== docId));
  }, []);

  /**
   * Handle the @-menu selection. Routes by discriminated-union kind:
   *   - 'file' → insert `@<path>` into the textarea (existing behavior)
   *   - 'office' → add the ChatOfficeRef to officeRefs
   *   - 'office-import' → call importOfficeReference then add the ref
   */
  const handleAtFileSelect = useCallback(
    async (selection: AtFileSelection) => {
      if (selection.kind === 'file') {
        insertAtFilePath(selection.path);
        return;
      }
      if (selection.kind === 'office') {
        addOfficeRef(selection.ref);
        return;
      }
      // kind === 'office-import'
      if (!effectiveWorkspacePath) {
        // No workspace bound — surface a friendly error rather than calling
        // the gateway. Chat.tsx renders the WorkspaceBindModal entry point;
        // we still close the @ menu so the user isn't stuck.
        console.warn('[ChatInput] Office import requires a bound workspace');
        return;
      }
      try {
        const ref = await importOfficeReference(effectiveWorkspacePath, selection.result);
        addOfficeRef(ref);
      } catch (e) {
        console.error('[ChatInput] Office import failed', e);
      }
    },
    [effectiveWorkspacePath, insertAtFilePath, addOfficeRef],
  );

  const handleAtFileClose = useCallback(() => {
    if (atQuery.query === null) return;
    const newValue = value.slice(0, atQuery.startIdx) + value.slice(atQuery.endIdx);
    setValue(newValue);
    setCursorPos(atQuery.startIdx);
  }, [value, atQuery]);

  const handleSend = () => {
    if (!value.trim() || isLoading) return;
    onSend(value.trim(), {
      knowledgeRefs: knowledgeRefs.length > 0 ? knowledgeRefs : undefined,
      attachments: files.length > 0 ? files : undefined,
      images: images.length > 0 ? images : undefined,
      officeRefs: officeRefs.length > 0 ? officeRefs : undefined,
    });
    setValue('');
    setKnowledgeRefs([]);
    setOfficeRefs([]);
    clearAll();
  };

  const handleSlashSelect = useCallback(
    (cmd: SlashCommand) => {
      setSlashMenuOpen(false);

      if (cmd.mode === 'clear') {
        setValue('');
        onClear?.();
        return;
      }

      // M4: /compact 是真实 action（后端会话压缩），不再作为提示词发给 LLM
      if (cmd.mode === 'compact') {
        setValue('');
        onCompact?.();
        return;
      }

      if (cmd.mode === 'help') {
        const helpText = slashCommands.map((c) => `/${c.name} — ${c.description}`).join('\n');
        setValue('');
        onSend(`可用命令列表：\n${helpText}`);
        return;
      }

      // Path B: SKILL.md skill — invoke via execute API and send returned content.
      // On failure, fall back to prompt-style execution so the user can still
      // talk about the skill even if the executor is unavailable.
      if (cmd.mode === 'skill' && cmd.skillName) {
        const parts = value.split(/\s+/);
        const args = parts.slice(1).join(' ');
        const skillName = cmd.skillName;
        skillsApi
          .execute(skillName, { args: { query: args } })
          .then((result) => {
            const body =
              typeof result.content === 'string' ? result.content : `/${skillName} ${args}`.trim();
            onSend(body);
            setValue('');
          })
          .catch(() => {
            // Fall back to prompt-style: send the raw "/skill args" as instruction
            const prompt = commandToPrompt({ ...cmd, mode: 'prompt', name: skillName }, args);
            onSend(prompt);
            setValue('');
          });
        return;
      }

      // prompt 模式：提取参数并转为提示词
      const parts = value.split(/\s+/);
      const args = parts.slice(1).join(' ');
      const prompt = commandToPrompt(cmd, args);
      setValue('');
      onSend(prompt);
    },
    [value, onSend, onClear, onCompact, slashCommands],
  );

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

  const toggleKnowledgeRef = (doc: (typeof KNOWLEDGE_DOCS)[number]) => {
    setKnowledgeRefs((prev) =>
      prev.find((r) => r.id === doc.id)
        ? prev.filter((r) => r.id !== doc.id)
        : [...prev, { id: doc.id, title: doc.title }],
    );
  };

  const handleChange = (newValue: string) => {
    setValue(newValue);
    setCursorPos(newValue.length);

    // Phase 6: /btw 拦截（优先级高于普通 slash 命令）
    const btwMatch = newValue.match(/^\/btw\s+(.+)$/);
    if (btwMatch) {
      btw.open(btwMatch[1]);
      setValue('');
      return;
    }

    // 检测 slash 命令
    if (newValue.startsWith('/')) {
      const query = newValue.slice(1).split(/\s/)[0] ?? '';
      // Path B: merge static commands with dynamically loaded SKILL.md slash commands.
      const merged = mergeSlashCommands(dynamicSlashCommands);
      const lower = query.toLowerCase();
      const filtered = merged.filter(
        (cmd) => cmd.name.toLowerCase().includes(lower) || cmd.label.toLowerCase().includes(lower),
      );
      if (filtered.length > 0) {
        setSlashCommands(filtered);
        setSlashSelectedIndex(0);
        setSlashMenuOpen(true);
      } else {
        setSlashMenuOpen(false);
      }
    } else {
      setSlashMenuOpen(false);
    }
  };

  // Effective sessionId is read by the AtFileMenu through the workspace
  // context; expose a hook here so future tests can assert on it without
  // reaching into the closure.
  void effectiveSessionId;

  return (
    <InputCard
      value={value}
      onChange={handleChange}
      onSubmit={handleSend}
      placeholder={placeholder ?? t('chat.placeholder')}
      disabled={disabled}
      isLoading={isLoading}
      onInterrupt={onInterrupt}
      files={files}
      images={images}
      knowledgeRefs={knowledgeRefs}
      officeRefs={officeRefs}
      onRemoveFile={removeFile}
      onRemoveImage={removeImage}
      onRemoveKnowledge={(idx) => setKnowledgeRefs((prev) => prev.filter((_, i) => i !== idx))}
      onRemoveOfficeRef={removeOfficeRef}
      knowledgeDocs={KNOWLEDGE_DOCS}
      showKnowledgeSelector={showKnowledgeSelector}
      onToggleKnowledgeSelector={setShowKnowledgeSelector}
      onToggleKnowledge={(docId) => {
        const doc = KNOWLEDGE_DOCS.find((d) => d.id === docId);
        if (doc) toggleKnowledgeRef(doc);
      }}
      onImageSelect={handleImageSelect}
      onFileSelect={handleFileSelect}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      isDragOver={isDragOver}
      showSlashMenu={slashMenuOpen}
      slashCommands={slashCommands}
      slashSelectedIndex={slashSelectedIndex}
      onSlashSelect={handleSlashSelect}
      atFileMenu={
        atQuery.query !== null && (
          <AtFileMenu
            query={atQuery.query}
            onSelect={(selection) => {
              void handleAtFileSelect(selection);
            }}
            onClose={handleAtFileClose}
          />
        )
      }
      hint={t('chat.hint')}
    />
  );
}
