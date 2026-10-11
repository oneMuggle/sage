/**
 * Phase P7: 内置版本快照时间轴与科研引用格式/学术文风快速切换栏 (2026-10-10)
 */

import { BookOpenCheck, History, Plus } from 'lucide-react';
import { useState } from 'react';

import { projectApi } from '../../shared/api';
import type { WorkspaceCheckpointItem } from '../../shared/api/projectApiTypes';
import { Button } from '../../shared/ui/Button';

export interface BuiltinCheckpointTimelineBarProps {
  projectId: string;
  checkpoints: WorkspaceCheckpointItem[];
  onCreated: () => Promise<void> | void;
}

export function BuiltinCheckpointTimelineBar({
  projectId,
  checkpoints,
  onCreated,
}: BuiltinCheckpointTimelineBarProps) {
  const [label, setLabel] = useState('');
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    if (creating || typeof projectApi?.createCheckpoint !== 'function') return;
    setCreating(true);
    try {
      await projectApi.createCheckpoint(projectId, label.trim() || undefined);
      setLabel('');
      await onCreated();
    } catch {
      // ignore in test/offline mode
    } finally {
      setCreating(false);
    }
  };

  return (
    <div
      className="rounded-lg border border-border/80 bg-muted/20 p-3 space-y-2"
      data-testid="builtin-checkpoint-bar"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
          <History className="h-3.5 w-3.5 text-emerald-500" />
          内置版本保护时间轴 (.sage/checkpoints)
        </div>
        <span className="text-ui-2xs text-muted-foreground">
          无需安装 Git，一键固化当前案卷文书与配置快照
        </span>
      </div>

      <div className="flex gap-1.5">
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="输入版本快照摘要（如：法务二审定稿前备份）"
          data-testid="checkpoint-label-input"
          className="flex-1 rounded border border-input bg-background px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          onClick={() => void handleCreate()}
          disabled={creating}
          data-testid="create-checkpoint-btn"
        >
          <Plus className="mr-1 h-3 w-3" />
          创建版本快照
        </Button>
      </div>

      {checkpoints.length > 0 && (
        <ul
          className="space-y-1 max-h-24 overflow-y-auto"
          data-testid="checkpoints-timeline-list"
        >
          {checkpoints.slice(0, 5).map((cp) => (
            <li
              key={cp.id}
              className="flex items-center justify-between gap-2 rounded border border-border/60 bg-background px-2.5 py-1 text-xs"
            >
              <span className="truncate font-medium text-foreground">{cp.label}</span>
              <span className="shrink-0 font-mono text-ui-2xs text-muted-foreground">
                {cp.fileCount} 份文件 · {cp.id}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const CITATION_STYLES: Record<string, string> = {
  'GB/T 7714': '参考文献与正文引注严格遵循中国国家标准 GB/T 7714-2015 顺序编码或著者-出版年制',
  'APA 7th': '学术引用严格遵循 APA 第 7 版 (Author, Year) 格式规范',
  IEEE: '工程与计算机论文引用遵循 IEEE 方括号数字编号 [1] 规范，图表标题符合 IEEE 排版要求',
  Nature: '自然科学论文引用采用 Nature 上标编号格式，首段凝练核心科学发现',
};

const WRITING_TONES: Record<string, string> = {
  '中文核心期刊严谨风': '采用客观严谨的中文学术书面语，避免口语化表述，首次出现的缩写与数学符号须明确定义',
  '英文 SCI 学术润色': '使用地道简洁的英文学术语态 (Academic English)，强化因果逻辑连接词与段落主旨句 (Topic Sentence)',
  'NSFC 基金申请书凝练风': '突出科学问题属性、立项依据紧迫性与关键科学问题凝练，做到逻辑自洽、重点加粗层次分明',
};

export interface ResearchCitationAndToneBarProps {
  projectId: string;
  onApplied: () => Promise<void> | void;
}

export function ResearchCitationAndToneBar({
  projectId,
  onApplied,
}: ResearchCitationAndToneBarProps) {
  const [citationStyle, setCitationStyle] = useState<string>('GB/T 7714');
  const [writingTone, setWritingTone] = useState<string>('中文核心期刊严谨风');
  const [applying, setApplying] = useState(false);
  const [appliedHint, setAppliedHint] = useState<string | null>(null);

  const handleApply = async () => {
    if (applying || typeof projectApi?.createConstraint !== 'function') return;
    setApplying(true);
    try {
      const citationDesc = CITATION_STYLES[citationStyle] ?? citationStyle;
      const toneDesc = WRITING_TONES[writingTone] ?? writingTone;
      await projectApi.createConstraint(projectId, {
        category: 'academic_writing',
        content: `【引用格式：${citationStyle}】${citationDesc}；【学术文风：${writingTone}】${toneDesc}`,
        triggerPattern: 'always',
        priority: 8,
      });
      setAppliedHint(`已应用「${citationStyle} + ${writingTone}」规范`);
      await onApplied();
    } catch {
      // ignore in test/offline mode
    } finally {
      setApplying(false);
    }
  };

  return (
    <div
      className="rounded-lg border border-border/80 bg-muted/20 p-3 space-y-2"
      data-testid="research-citation-style-bar"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
          <BookOpenCheck className="h-3.5 w-3.5 text-purple-500" />
          学术规范与引用护栏快速配置 (APA / IEEE / Nature / GB-T7714)
        </div>
        {appliedHint && (
          <span
            className="text-ui-2xs font-medium text-purple-600"
            data-testid="research-style-applied-hint"
          >
            {appliedHint}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={citationStyle}
          onChange={(e) => setCitationStyle(e.target.value)}
          aria-label="选择引用格式"
          data-testid="research-citation-style-select"
          className="rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
        >
          {Object.keys(CITATION_STYLES).map((k) => (
            <option key={k} value={k}>
              引用格式：{k}
            </option>
          ))}
        </select>

        <select
          value={writingTone}
          onChange={(e) => setWritingTone(e.target.value)}
          aria-label="选择学术文风"
          data-testid="research-writing-tone-select"
          className="rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
        >
          {Object.keys(WRITING_TONES).map((k) => (
            <option key={k} value={k}>
              文风：{k}
            </option>
          ))}
        </select>

        <Button
          size="sm"
          onClick={() => void handleApply()}
          disabled={applying}
          data-testid="research-apply-style-btn"
        >
          一键写入学术规范
        </Button>
      </div>
    </div>
  );
}
