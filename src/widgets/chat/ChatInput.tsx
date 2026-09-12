import { memo, useCallback, useEffect, useState } from 'react';

import { AtFileMenu, useAtFileQuery, useBtwCommand } from '../../features/chat';
import { importOfficeReference } from '../../features/office/importOfficeReference';
import { knowledgeApi, skillsApi } from '../../shared/api';
import { type AtFileSelection } from '../../shared/api/fileSearchClient';
import type { ChatOfficeRef } from '../../shared/api/types';
import { useFileUpload } from '../../shared/lib/hooks/useFileUpload';
import { useSessionDraft } from '../../shared/lib/hooks/useSessionDraft';
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
      /** PM1 (round8): 计划模式 —— 只读调研 + 计划产出（/plan 命令）。 */
      planMode?: boolean;
      knowledgeRefs?: { id: string; title: string }[];
      attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
      images?: { name: string; size: number; type: string; dataUrl?: string }[];
      /**
       * Task 7 (2026-07-26): managed Office references from the @-menu.
       * The Chat page forwards these into `chatApi.chatStream`'s 5th arg
       * so the LLM can see the office doc summaries.
       */
      officeRefs?: readonly ChatOfficeRef[];
      /**
       * Multi-Agent Orchestration: /orchestrate → force_multi、/single → force_single。
       * Wave 3 C6: 编排模式条可传 'auto' | 'force_multi' | 'template:<id>'。
       * 普通消息不传（undefined → 后端 auto）。
       */
      orchestrationMode?: string;
    },
  ) => void;
  onInterrupt?: () => void;
  onClear?: () => void;
  /**
   * M4: /compact slash action 回调。由 Chat 页面实现（调用 session_compact
   * IPC + toast + 重载消息）。未提供时 /compact 静默无操作。
   */
  onCompact?: () => void;
  /**
   * Task 12 (2026-08-03): /learn slash action 回调。由 Chat 页面实现
   * （调用 learnApi + toast + 跳转到 Pending Drafts tab）。未提供时
   * /learn 静默无操作。
   */
  onLearn?: () => void;
  isLoading?: boolean;
  disabled?: boolean;
  placeholder?: string;
  /**
   * U5' (对标增强第五轮批次 A): 编辑重发——外部注入输入框内容。
   * `nonce` 变化时用 `text` 覆盖当前草稿（点击同一条消息两次也能重注入）。
   */
  injectedDraft?: { text: string; nonce: number } | null;
  /**
   * U5': 编辑重发提示条。非 null 时在输入卡片上方渲染"正在编辑重发"
   * 横条，onCancel 由 Chat 页清除编辑态。
   */
  editResendNotice?: { onCancel: () => void } | null;
  /**
   * Optional workspace root — kept for backwards-compat with callers that
   * haven't migrated to the SessionWorkspaceProvider yet. When the
   * provider is mounted (Chat page via SessionWorkspaceProvider), the
   * menu reads sessionId + workspacePath from there instead.
   */
  workspacePath?: string;
}

function ChatInputInner({
  onSend,
  onInterrupt,
  onClear,
  onCompact,
  onLearn,
  isLoading = false,
  disabled = false,
  placeholder,
  workspacePath,
  injectedDraft,
  editResendNotice,
}: ChatInputProps) {
  const { t } = useI18n();

  // Workspace context — provides sessionId + binding for the @ menu.
  // Falls back to the legacy `workspacePath` prop for callers that don't
  // mount the provider (e.g. some legacy tests). Use the optional variant
  // so legacy tests that don't mount the provider don't throw.
  const workspaceContext = useOptionalWorkspaceContext();
  const effectiveWorkspacePath = workspaceContext?.binding?.workspacePath ?? workspacePath;
  // sessionId is used by the AtFileMenu itself (via useOptionalWorkspaceContext);
  // expose on the closure so future tests can assert on it.
  const effectiveSessionId = workspaceContext?.sessionId ?? null;

  // Per-session draft persistence (U13 from OpenWorker)
  const [value, setValue] = useSessionDraft(effectiveSessionId);

  // U5': 编辑重发注入——nonce 变化时用外部文本覆盖当前草稿
  // （依赖只取 nonce：同一条消息重复点击也要重注入，text 变化不单独触发）。
  const injectedNonce = injectedDraft?.nonce;
  useEffect(() => {
    if (injectedDraft && injectedNonce != null) {
      setValue(injectedDraft.text);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只由 nonce 驱动
  }, [injectedNonce]);

  const [cursorPos, setCursorPos] = useState(0);
  const [knowledgeRefs, setKnowledgeRefs] = useState<{ id: string; title: string }[]>([]);
  const [showKnowledgeSelector, setShowKnowledgeSelector] = useState(false);
  const [slashMenuOpen, setSlashMenuOpen] = useState(false);
  const [slashCommands, setSlashCommands] = useState<SlashCommand[]>([]);
  const [slashSelectedIndex, setSlashSelectedIndex] = useState(0);
  // U3 (P5): 知识引用接真实知识库 —— 此前是硬编码演示列表, 用户勾选的
  // '引用'并非真实存在的文档, 极易误导。加载失败降级为空态不阻塞输入。
  const [knowledgeDocs, setKnowledgeDocs] = useState<KnowledgeDocType[]>([]);
  useEffect(() => {
    let cancelled = false;
    knowledgeApi
      .list()
      .then((docs) => {
        if (cancelled) return;
        setKnowledgeDocs(docs.map((d) => ({ id: d.id, title: d.title, desc: d.description })));
      })
      .catch(() => {
        if (!cancelled) setKnowledgeDocs([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  // Path B: dynamic SKILL.md slash command names fetched from the backend.
  // On fetch failure we silently fall back to an empty list (no slash skills).
  const [dynamicSlashCommands, setDynamicSlashCommands] = useState<DynamicSlashSkill[]>([]);

  // Task 7 (2026-07-26): managed Office refs attached via the @ menu.
  // Dedupe by docId (immutable state — every update is a new array).
  const [officeRefs, setOfficeRefs] = useState<readonly ChatOfficeRef[]>([]);

  // Wave 3 C6 (2026-08-15): 编排模式偏好（组件 state —— YAGNI 不写 settings）。
  // auto = LLM 二分类；force_multi = 强制编排；template:<id> = 确定性模板。
  const [orchMode, setOrchMode] = useState('auto');

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
    handlePaste,
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
    [value, atQuery, setValue],
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
  }, [value, atQuery, setValue]);

  const handleSend = () => {
    // RT5 (round7): 运行中允许发送 —— onSend（useChat.sendMessage）按会话
    // 活跃流先走 steering 注入当前 run，失败回退队列；不再 UI 硬拦截。
    if (!value.trim()) return;
    onSend(value.trim(), {
      knowledgeRefs: knowledgeRefs.length > 0 ? knowledgeRefs : undefined,
      attachments: files.length > 0 ? files : undefined,
      images: images.length > 0 ? images : undefined,
      officeRefs: officeRefs.length > 0 ? officeRefs : undefined,
      // Wave 3 C6: auto 不传键 → 保持既有 undefined → auto 语义；
      // force_multi / template:<id> 显式透传。
      ...(orchMode !== 'auto' ? { orchestrationMode: orchMode } : {}),
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

      // M4: /compact 是真实 action（后端会话压缩），不再作为提示词发给 LLM。
      // MEDIUM-1: 流式中 / 禁用态选择 /compact 必须是 no-op —— 对齐 handleSend
      // 的 isLoading 守卫，防止流式期间触发压缩（并发手动压缩会写出重复续接行；
      // 后端 409 是兜底，前端守卫才是第一道防线）。
      if (cmd.mode === 'compact') {
        if (isLoading || disabled) return;
        setValue('');
        onCompact?.();
        return;
      }

      // Task 12 (2026-08-03): /learn 触发 Background Review，
      // 由 Chat 页面负责调用 learnApi + toast + 跳转到 Pending Drafts tab。
      // 对齐 /compact 的守卫：流式/禁用态下为 no-op。
      if (cmd.mode === 'learn') {
        if (isLoading || disabled) return;
        setValue('');
        onLearn?.();
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

      // PM2 (round8): /plan 计划模式 —— 以 planMode 立即发送剩余文本；
      // run 完成后 Chat 页出批准条，批准后普通消息衔接执行。
      if (cmd.mode === 'plan') {
        if (isLoading || disabled) return;
        const goal = value.trim().replace(new RegExp('^/plan', 'i'), '').trim();
        setValue('');
        if (goal) onSend(goal, { planMode: true });
        return;
      }

      // Multi-Agent Orchestration override（tool-toggle 门的手动逃生门）:
      // /orchestrate → force_multi、/single → force_single。正文随消息发送；
      // 纯命令无正文 → 用法提示（对齐 help/skill 命令的处理模式）。
      if (cmd.name === 'orchestrate' || cmd.name === 'single') {
        const parts = value.split(/\s+/);
        const args = parts.slice(1).join(' ');
        setValue('');
        if (!args) {
          onSend(`用法：/${cmd.name} 你的任务描述`);
          return;
        }
        onSend(args, {
          orchestrationMode: cmd.name === 'orchestrate' ? 'force_multi' : 'force_single',
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
    [value, onSend, onClear, onCompact, onLearn, slashCommands, isLoading, disabled, setValue],
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

  // Phase 4 (2026-09-12): audio attachment upload handler
  const handleAudioAttachment = (attachment: {
    mediaRef: { id: string; mime_type: string; file_size: number };
    apiUrl: string;
  }) => {
    // TODO: integrate with message sending (attach to next user message)
    console.log('[ChatInput] Audio attachment uploaded:', attachment);
  };

  const toggleKnowledgeRef = (doc: KnowledgeDocType) => {
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
    <div className="flex flex-col">
      {editResendNotice && (
        <div
          data-testid="edit-resend-banner"
          className="mx-4 mb-1 px-3 py-1.5 rounded-t-radius-md bg-primary/10 border border-b-0 border-primary/30 text-xs text-text flex items-center gap-2"
        >
          <span className="flex-1">{t('chat.edit_resend_notice')}</span>
          <button
            type="button"
            onClick={editResendNotice.onCancel}
            aria-label={t('chat.edit_resend_cancel')}
            className="px-1.5 py-0.5 rounded hover:bg-bg-hover text-text-secondary"
          >
            {t('chat.edit_resend_cancel')}
          </button>
        </div>
      )}
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
        knowledgeDocs={knowledgeDocs}
        showKnowledgeSelector={showKnowledgeSelector}
        onToggleKnowledgeSelector={setShowKnowledgeSelector}
        onToggleKnowledge={(docId) => {
          const doc = knowledgeDocs.find((d) => d.id === docId);
          if (doc) toggleKnowledgeRef(doc);
        }}
        onImageSelect={handleImageSelect}
        onFileSelect={handleFileSelect}
        onAudioAttachment={handleAudioAttachment}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onPaste={handlePaste}
        isDragOver={isDragOver}
        showSlashMenu={slashMenuOpen}
        slashCommands={slashCommands}
        slashSelectedIndex={slashSelectedIndex}
        onSlashSelect={handleSlashSelect}
        onSlashHighlight={setSlashSelectedIndex}
        onSlashClose={() => setSlashMenuOpen(false)}
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
        orchModeBar={
          <div className="flex items-center gap-2 px-2 py-1 border-b border-border">
            <label className="text-xs text-text-tertiary">{t('chat.orchMode.label')}</label>
            <select
              data-testid="orch-mode-select"
              value={orchMode}
              onChange={(e) => setOrchMode(e.target.value)}
              className="px-2 py-0.5 text-xs border border-border rounded bg-bg text-text"
            >
              <option value="auto">{t('chat.orchMode.auto')}</option>
              <option value="force_multi">{t('chat.orchMode.forceMulti')}</option>
              <option value="template:research-write">
                {t('chat.orchMode.templateResearchWrite')}
              </option>
              <option value="template:gather-analyze-report">
                {t('chat.orchMode.templateGatherAnalyzeReport')}
              </option>
            </select>
          </div>
        }
        hint={t('chat.hint')}
      />
    </div>
  );
}

// memo (F1): 流式期间 Chat 每 token 重渲染, 调用方已稳定化回调/对象 props,
// 输入区自身状态不变时整块跳过重渲染。
export const ChatInput = memo(ChatInputInner);
