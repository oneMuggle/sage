// src/widgets/chat/changes/SplitDiff.tsx
//
// P1-3.8 (UI 优化方案 2026-09-13): 分栏 (side-by-side) diff 视图。
// 把 unified diff 字符串通过 splitDiffParser 解析后渲染为左右两栏表格。
// 颜色使用 Tailwind dark: 变体自动适配亮/暗主题,无需读取 useTheme。
//
// 设计要点:
// - 表头两列 "原始" / "修改后" 对齐左右两侧
// - header 行跨四列 (浅灰底)
// - context 行两侧文本相同,无高亮
// - modify 行左红右绿 (表示被替换的内容)
// - remove 行仅左侧红色,右侧留空
// - add 行仅右侧绿色,左侧留空
// - 行号列固定宽度,select-none 防止误选
// - 等宽字体 + white-space-pre 保持缩进
//
// 本组件只读、不涉及 per-hunk 反向应用;如需撤销改动,请切换回 unified 视图。

import { useMemo } from 'react';

import { parseUnifiedDiff } from './splitDiffParser';

interface SplitDiffProps {
  /** 后端返回的 unified diff 字符串 (可能已被截断,截断提示由父组件渲染) */
  diff: string;
}

export function SplitDiff({ diff }: SplitDiffProps) {
  const rows = useMemo(() => parseUnifiedDiff(diff), [diff]);

  return (
    <div className="font-mono text-xs overflow-x-auto" data-testid="split-diff">
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-bg-muted/50 text-text-secondary">
            <th className="w-10 py-1 text-right pr-2 font-normal select-none">行</th>
            <th className="py-1 px-2 text-left font-normal">原始</th>
            <th className="w-10 py-1 text-right pr-2 font-normal select-none">行</th>
            <th className="py-1 px-2 text-left font-normal">修改后</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            if (row.kind === 'header') {
              return (
                <tr key={i} data-testid={`split-diff-header-${i}`}>
                  <td
                    colSpan={4}
                    className="px-2 py-0.5 text-text-muted bg-bg-muted/40 whitespace-pre"
                  >
                    {row.oldText}
                  </td>
                </tr>
              );
            }

            const leftBg =
              row.kind === 'modify'
                ? 'bg-red-100 dark:bg-red-900/25'
                : row.kind === 'remove'
                  ? 'bg-red-50 dark:bg-red-900/15'
                  : '';
            const rightBg =
              row.kind === 'modify'
                ? 'bg-green-100 dark:bg-green-900/25'
                : row.kind === 'add'
                  ? 'bg-green-50 dark:bg-green-900/15'
                  : '';

            return (
              <tr key={i} data-testid={`split-diff-row-${i}`}>
                <td
                  className="w-10 text-right pr-2 text-text-muted select-none align-top"
                  aria-label="原文件行号"
                >
                  {row.oldLine ?? ''}
                </td>
                <td className={`px-2 whitespace-pre align-top ${leftBg}`}>{row.oldText}</td>
                <td
                  className="w-10 text-right pr-2 text-text-muted select-none align-top"
                  aria-label="新文件行号"
                >
                  {row.newLine ?? ''}
                </td>
                <td className={`px-2 whitespace-pre align-top ${rightBg}`}>{row.newText}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
