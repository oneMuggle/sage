import { useCallback, useEffect, useState } from 'react';

import { AtFileMenu, useAtFileQuery, useBtwCommand } from '../../features/chat';
import { skillsApi } from '../../shared/api';
import { useFileUpload } from '../../shared/lib/hooks/useFileUpload';
import { useI18n } from '../../shared/lib/i18n';

import { InputCard, type KnowledgeDocType } from './InputCard';
import { commandToPrompt, mergeSlashCommands, type SlashCommand } from './slashCommands';

interface ChatInputProps {
  onSend: (
    message: string,
    options?: {
      knowledgeRefs?: { id: string; title: string }[];
      attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
      images?: { name: string; size: number; type: string; dataUrl?: string }[];
    },
  ) => void;
  onInterrupt?: () => void;
  onClear?: () => void;
  isLoading?: boolean;
  disabled?: boolean;
  placeholder?: string;
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
  isLoading = false,
  disabled = false,
  placeholder,
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
  const [dynamicSlashCommands, setDynamicSlashCommands] = useState<string[]>([]);

  // Phase 6: @文件提及 + /btw 补充消息
  const btw = useBtwCommand();
  const atQuery = useAtFileQuery(value, cursorPos);

  // Fetch user-invocable SKILL.md skill names on mount. The list is loaded once;
  // ChatInput can be re-mounted or the user can click a "refresh" affordance later
  // if needed (out of scope for Path B).
  useEffect(() => {
    skillsApi
      .listSlashCommands()
      .then(setDynamicSlashCommands)
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

  const handleSend = () => {
    if (!value.trim() || isLoading) return;
    onSend(value.trim(), {
      knowledgeRefs: knowledgeRefs.length > 0 ? knowledgeRefs : undefined,
      attachments: files.length > 0 ? files : undefined,
      images: images.length > 0 ? images : undefined,
    });
    setValue('');
    setKnowledgeRefs([]);
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
    [value, onSend, onClear, slashCommands],
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
      onRemoveFile={removeFile}
      onRemoveImage={removeImage}
      onRemoveKnowledge={(idx) => setKnowledgeRefs((prev) => prev.filter((_, i) => i !== idx))}
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
            onSelect={(path) => {
              const newValue =
                value.slice(0, atQuery.startIdx) + '@' + path + ' ' + value.slice(atQuery.endIdx);
              setValue(newValue);
              setCursorPos(atQuery.startIdx + 1 + path.length + 1);
            }}
            onClose={() => {
              const newValue = value.slice(0, atQuery.startIdx) + value.slice(atQuery.endIdx);
              setValue(newValue);
              setCursorPos(atQuery.startIdx);
            }}
          />
        )
      }
      hint={t('chat.hint')}
    />
  );
}
