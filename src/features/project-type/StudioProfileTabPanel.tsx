/**
 * Phase P18: L3 项目演化记忆画像面板 (MEMORY.md)
 * 支持四形态画像推荐预设胶囊与一键导出 MEMORY.md Markdown 视图
 */

import { Copy, Plus, Sparkles, Trash2 } from 'lucide-react';
import { useState } from 'react';

import type { ProjectType } from '../../shared/api/projectApiTypes';
import type { ProjectProfileEntry } from '../../shared/api/types';
import { Button } from '../../shared/ui/Button';

interface ProfilePresetItem {
  category: string;
  label: string;
  content: string;
}

const PROFILE_PRESETS_BY_TYPE: Record<ProjectType, ProfilePresetItem[]> = {
  coding: [
    {
      category: 'architecture',
      label: 'IPC 契约一致性',
      content: '前后端 IPC 契约须与 electron/ipc-manifest.json 严格保持同步，严禁绕过桥接层直连。',
    },
    {
      category: 'convention',
      label: '单文件 800 行红线',
      content: '前端与后端单文件严格保持 <= 800 行，超过阈值须按职责拆分子模块。',
    },
  ],
  business: [
    {
      category: 'convention',
      label: '大小写金额双轨核对',
      content: '所有合同、请示与结算报表中的金额须同时标注人民币大写与阿拉伯数字并交叉核验。',
    },
    {
      category: 'decision',
      label: '定稿签发前固化快照',
      content: '每次向外部提交或归档正式版文书前，须创建 .sage/checkpoints 版本快照留痕。',
    },
  ],
  research: [
    {
      category: 'convention',
      label: '零幻觉文献引用铁律',
      content: '所有核心学术论点与对比结论必须绑定已入库文献 Citation Key，严禁虚构任何 DOI 或年份。',
    },
    {
      category: 'architecture',
      label: '实验可复现性基线',
      content: '所有主实验与消融实验须固定随机种子并完整记录数据集划分与超参数配置。',
    },
  ],
  personal: [
    {
      category: 'convention',
      label: '原子化卡片盒笔记',
      content: '每则永久笔记聚焦单一概念，使用 [[双链概念]] 建立跨笔记知识图谱连接。',
    },
    {
      category: 'goal',
      label: '每周行动项提炼',
      content: '定期回顾收件箱笔记并提炼可执行的下一步行动项 (Next Actions)。',
    },
  ],
};

export interface StudioProfileTabPanelProps {
  projectPath: string;
  projectType?: ProjectType;
  profileEntries: ProjectProfileEntry[];
  profileCategory: string;
  onCategoryChange: (cat: string) => void;
  profileDraft: string;
  onDraftChange: (val: string) => void;
  savingProfile: boolean;
  onAddEntry: () => Promise<void> | void;
  onDeleteEntry: (entryId: string) => Promise<void> | void;
}

export function StudioProfileTabPanel({
  projectPath,
  projectType = 'coding',
  profileEntries,
  profileCategory,
  onCategoryChange,
  profileDraft,
  onDraftChange,
  savingProfile,
  onAddEntry,
  onDeleteEntry,
}: StudioProfileTabPanelProps) {
  const [copiedMd, setCopiedMd] = useState(false);
  const presets = PROFILE_PRESETS_BY_TYPE[projectType] ?? PROFILE_PRESETS_BY_TYPE.coding;

  const handleCopyMarkdown = async () => {
    const lines = [
      `# MEMORY.md (${projectPath})`,
      '',
      ...profileEntries.map((e) => `- **[${e.category}]** ${e.content}`),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedMd(true);
      setTimeout(() => setCopiedMd(false), 2000);
    } catch {
      // ignore in test env
    }
  };

  return (
    <div className="space-y-3" data-testid="project-profile-studio-panel">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
        <div>
          项目级冻结记忆画像（<code className="font-mono">MEMORY.md</code> · 绑定路径{' '}
          <code className="font-mono">{projectPath}</code>
          ），仅在当前项目会话中注入系统提示词，保障跨项目语境隔离与 Prefix Cache 命中率。
        </div>
        {profileEntries.length > 0 && (
          <button
            type="button"
            onClick={() => void handleCopyMarkdown()}
            data-testid="studio-profile-copy-md-btn"
            className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-ui-2xs font-medium text-foreground hover:bg-muted"
          >
            <Copy className="h-3 w-3 text-primary" />
            {copiedMd ? '已复制 MEMORY.md' : '复制 MEMORY.md 视图'}
          </button>
        )}
      </div>

      <div
        className="flex flex-wrap items-center gap-1.5"
        data-testid="studio-profile-presets-bar"
      >
        <span className="inline-flex items-center gap-1 text-ui-2xs text-muted-foreground">
          <Sparkles className="h-3 w-3 text-primary" />
          当前形态推荐画像条目：
        </span>
        {presets.map((preset, idx) => (
          <button
            key={preset.label}
            type="button"
            data-testid={`studio-profile-preset-${idx}`}
            onClick={() => {
              onCategoryChange(preset.category);
              onDraftChange(preset.content);
            }}
            className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
          >
            [{preset.category}] {preset.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <select
          value={profileCategory}
          onChange={(e) => onCategoryChange(e.target.value)}
          aria-label="选择画像类别"
          data-testid="studio-profile-category"
          className="rounded-md border border-input bg-background px-2.5 py-1.5 text-xs text-foreground"
        >
          <option value="convention">约定 (convention)</option>
          <option value="architecture">架构/方法论 (architecture)</option>
          <option value="decision">决策/审校口径 (decision)</option>
          <option value="goal">核心目标/研究问题 (goal)</option>
          <option value="note">阶段发现/备注 (note)</option>
        </select>
        <input
          type="text"
          value={profileDraft}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder="输入要长期固化到本项目的约定、决策或核心目标..."
          data-testid="studio-profile-input"
          className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs"
        />
        <Button
          size="sm"
          onClick={() => void onAddEntry()}
          disabled={!profileDraft.trim() || savingProfile}
          data-testid="studio-profile-add-btn"
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          添加画像条目
        </Button>
      </div>
      {profileEntries.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
          当前项目暂无冻结画像条目
        </div>
      ) : (
        <div className="space-y-1.5" data-testid="studio-profile-list">
          {profileEntries.map((entry) => (
            <div
              key={entry.id}
              className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-xs"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-ui-2xs font-medium text-primary">
                  {entry.category}
                </span>
                <span className="truncate text-foreground">{entry.content}</span>
              </div>
              <button
                type="button"
                onClick={() => void onDeleteEntry(entry.id)}
                aria-label={`删除画像条目：${entry.content}`}
                data-testid={`studio-profile-delete-${entry.id}`}
                className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
