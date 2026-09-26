/**
 * FileWriteToolRenderer — 专用 write_file/edit_file 工具卡片。
 *
 * 显示: 文件路径（文件图标 + mono 路径）+ 操作类型。
 * 不显示 result（写文件操作的结果通常是简短的成功消息，不需要展开）。
 */

import { FileEdit, FilePlus } from 'lucide-react';

import type { ToolCall } from '../../../shared/lib/store';

import { ToolCallCard } from './ToolCallCard';

const FILE_TOOLS = new Set(['write_file', 'edit_file']);

export function isFileWriteTool(name: string): boolean {
  return FILE_TOOLS.has(name);
}

export function FileWriteToolRenderer({ tc }: { tc: ToolCall }) {
  const isEdit = tc.name === 'edit_file';
  const filePath = String(tc.args.file_path ?? tc.args.path ?? '');
  const fileName = filePath.split('/').pop() ?? filePath;
  const Icon = isEdit ? FileEdit : FilePlus;
  const verb = isEdit ? 'Edit' : tc.args.append ? 'Append to' : 'Write';

  return (
    <ToolCallCard
      tc={tc}
      title={
        <span className="flex items-center gap-1.5">
          <Icon className="w-3.5 h-3.5 text-primary shrink-0" />
          <span className="font-medium">{verb}</span>
          <code className="text-text truncate max-w-[200px]" title={filePath}>
            {fileName}
          </code>
        </span>
      }
      summary={
        filePath ? (
          <span className="text-[10px] max-w-[100px] truncate" title={filePath}>
            {filePath.length > 30 ? '…' + filePath.slice(-27) : filePath}
          </span>
        ) : undefined
      }
      defaultCollapsed
    >
      <div className="font-mono text-[11px] text-text-secondary py-0.5">{filePath}</div>
    </ToolCallCard>
  );
}
