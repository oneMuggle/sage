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
// right-panel R6 (2026-09-19): modify 行词级行内高亮 —— 复用 textDiff 的
// 字符级 diffSpans 把行内真正变化的部分染深色（GitHub / VSCode 观感）,
// 未变化的上下文保持行底色。单侧超 300 字符时 diffSpans 自动退化为
// 整行染色,与 office 预览同口径。
//
// 本组件只读、不涉及 per-hunk 反向应用;如需撤销改动,请切换回 unified 视图。

import { useMemo } from 'react';

import { diffSpans, type DiffSpan } from '../../../shared/lib/textDiff';

import { parseUnifiedDiff } from './splitDiffParser';

interface SplitDiffProps {
  /** 后端返回的 unified diff 字符串 (可能已被截断,截断提示由父组件渲染) */
  diff: string;
}

/** 行内片段染色: 变化段染深色,相同段保持行底色 */
function SpanText({ spans, side }: { spans: DiffSpan[]; side: 'del' | 'add' }) {
  if (spans.length === 0) return null;
  return (
    <>
      {spans.map((span, i) =>
        span.kind === 'same' ? (
          <span key={i}>{span.text}</span>
        ) : (
          <span
            key={i}
            className={
              side === 'del'
                ? 'rounded-sm bg-red-300/70 dark:bg-red-700/60'
                : 'rounded-sm bg-green-300/70 dark:bg-green-700/60'
            }
          >
            {span.text}
          </span>
        ),
      )}
    </>
  );
}

export function SplitDiff({ diff }: SplitDiffProps) {
  const rows = useMemo(() => parseUnifiedDiff(diff), [diff]);

  // 仅对 modify 行计算词级 spans（键为 rows 下标）;remove/add 行保持整行染色
  const wordSpans = useMemo(() => {
    const map = new Map<number, { before: DiffSpan[]; after: DiffSpan[] }>();
    rows.forEach((row, i) => {
      if (row.kind === 'modify' && row.oldText !== '' && row.newText !== '') {
        map.set(i, diffSpans(row.oldText, row.newText));
      }
    });
    return map;
  }, [rows]);

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
            const spans = wordSpans.get(i);

            return (
              <tr key={i} data-testid={`split-diff-row-${i}`}>
                <td
                  className="w-10 text-right pr-2 text-text-muted select-none align-top"
                  aria-label="原文件行号"
                >
                  {row.oldLine ?? ''}
                </td>
                <td className={`px-2 whitespace-pre align-top ${leftBg}`}>
                  {spans ? (
                    <SpanText spans={spans.before} side="del" />
                  ) : (
                    row.oldText
                  )}
                </td>
                <td
                  className="w-10 text-right pr-2 text-text-muted select-none align-top"
                  aria-label="新文件行号"
                >
                  {row.newLine ?? ''}
                </td>
                <td className={`px-2 whitespace-pre align-top ${rightBg}`}>
                  {spans ? <SpanText spans={spans.after} side="add" /> : row.newText}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
