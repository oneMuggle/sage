/**
 * 外部目录只读白名单面板 — 允许 AI 读取项目目录之外的文件。
 */

import { Check, Copy, FolderLock, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';

import type { ProjectType } from '../../shared/api/projectApiTypes';
import { Button } from '../../shared/ui/Button';

const ALLOWED_PATH_PRESETS: Record<ProjectType, Array<{ label: string; pattern: string }>> = {
  coding: [
    { label: '跨仓共享 SDK 目录', pattern: '../shared-sdk/**' },
    { label: '公共 API 契约规范库', pattern: '~/Documents/APISpecs/**' },
  ],
  business: [
    { label: '企业标准合同与公文范本库', pattern: '~/Documents/EnterpriseTemplates/**' },
    { label: '国家政策法规与行业标准库', pattern: '~/Documents/Regulations/**' },
  ],
  research: [
    { label: '全局 Zotero 文献 PDF 库', pattern: '~/Zotero/storage/**' },
    { label: '公共科研数据集只读目录', pattern: '~/Datasets/**' },
  ],
  personal: [
    { label: '网页剪藏归档库', pattern: '~/Documents/Clippings/**' },
    { label: '个人电子书与文献库', pattern: '~/Documents/Ebooks/**' },
  ],
};

export interface StudioAllowedPathsTabPanelProps {
  projectPath: string;
  projectType: ProjectType;
  allowedPaths: string[];
  newAllowedPath: string;
  onNewAllowedPathChange: (val: string) => void;
  savingPaths: boolean;
  onAddAllowedPath: () => Promise<void> | void;
  onQuickAddPresetPath: (pattern: string) => Promise<void> | void;
  onRemoveAllowedPath: (rule: string) => Promise<void> | void;
}

export function StudioAllowedPathsTabPanel({
  projectPath,
  projectType,
  allowedPaths,
  newAllowedPath,
  onNewAllowedPathChange,
  savingPaths,
  onAddAllowedPath,
  onQuickAddPresetPath,
  onRemoveAllowedPath,
}: StudioAllowedPathsTabPanelProps) {
  const [copiedPaths, setCopiedPaths] = useState(false);
  const presets = ALLOWED_PATH_PRESETS[projectType] ?? ALLOWED_PATH_PRESETS.coding;

  const handleCopyAllowedPaths = async () => {
    const lines = [
      `# 外部目录只读白名单 (${projectPath})`,
      '',
      ...allowedPaths.map((p) => `- \`${p}\``),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedPaths(true);
      setTimeout(() => setCopiedPaths(false), 2000);
    } catch {
      // ignore in test env
    }
  };

  return (
    <div className="space-y-3" data-testid="project-allowed-paths-panel">
      <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground space-y-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="font-medium text-foreground">
            读写非对称安全边界（Workspace Write + Allowed Paths Read-Only）
          </div>
          {allowedPaths.length > 0 && (
            <button
              type="button"
              onClick={() => void handleCopyAllowedPaths()}
              data-testid="allowed-paths-copy-md-btn"
              className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs font-medium text-foreground hover:bg-muted"
            >
              {copiedPaths ? (
                <Check className="h-3 w-3 text-emerald-500" />
              ) : (
                <Copy className="h-3 w-3 text-primary" />
              )}
              {copiedPaths ? '已复制白名单' : '复制白名单配置'}
            </button>
          )}
        </div>
        <p>
          • 主工作区目录（<code className="font-mono">{projectPath}</code>
          ）：允许 AI 读写文件与生成交付物。
        </p>
        <p>
          • 跨目录只读白名单（<code className="font-mono">allowed_paths</code>
          ）：适合挂载一般档案的「企业合同/公文范本库」、科研项目的「Zotero
          文献库或外部大型数据集」、代码项目的「共享 SDK 仓库」，仅允许只读检索，严禁写入篡改。
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-1.5" data-testid="allowed-paths-presets-bar">
        <span className="inline-flex items-center gap-1 text-ui-2xs text-muted-foreground">
          <FolderLock className="h-3 w-3 text-primary" />
          当前形态推荐只读挂载：
        </span>
        {presets.map((preset, idx) => {
          const alreadyAdded = allowedPaths.includes(preset.pattern);
          return (
            <button
              key={preset.pattern}
              type="button"
              disabled={alreadyAdded || savingPaths}
              onClick={() => void onQuickAddPresetPath(preset.pattern)}
              data-testid={`allowed-path-preset-${idx}`}
              className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs text-primary hover:bg-primary/10 disabled:opacity-50"
            >
              <Plus className="h-2.5 w-2.5" />
              {preset.label} ({preset.pattern})
            </button>
          );
        })}
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={newAllowedPath}
          onChange={(e) => onNewAllowedPathChange(e.target.value)}
          placeholder="输入外部只读参考目录路径或通配规则（如 D:/Templates/** 或 ~/Zotero/storage/**）"
          className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs font-mono"
        />
        <Button
          size="sm"
          onClick={() => void onAddAllowedPath()}
          disabled={!newAllowedPath.trim() || savingPaths}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          添加只读路径
        </Button>
      </div>

      {allowedPaths.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
          暂未配置额外只读路径（当前仅允许访问项目主目录 {projectPath}）
        </div>
      ) : (
        <div className="space-y-1.5">
          {allowedPaths.map((rule) => (
            <div
              key={rule}
              className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-xs"
            >
              <span className="font-mono text-foreground">{rule}</span>
              <button
                type="button"
                onClick={() => void onRemoveAllowedPath(rule)}
                disabled={savingPaths}
                className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                aria-label={`移除只读路径：${rule}`}
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
