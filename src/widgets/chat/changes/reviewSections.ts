// src/widgets/chat/changes/reviewSections.ts
//
// right-panel R6 (2026-09-19): "全部审查" 汇总视图的 diff 切分纯函数。
// 从 ReviewAll 组件中拆出（react-refresh 只允许组件文件导出组件），
// 可独立单测。

/** 一节 = 一个文件的 unified diff */
export interface ReviewFileSection {
  /** 新文件侧路径（删除文件取旧侧） */
  path: string;
  /** 该文件的 unified diff 文本（含文件头） */
  diffText: string;
  /** 二进制文件（无文本 hunk） */
  binary: boolean;
}

/**
 * 把多文件 unified diff 按 "diff --git" 行切分为逐文件小节。
 * 路径优先取 `+++ b/<path>`；删除文件（`+++ /dev/null`）回落到
 * `diff --git a/<old> b/<old>` 的旧侧。
 */
export function splitReviewSections(fullDiff: string): ReviewFileSection[] {
  if (!fullDiff.trim()) return [];
  const sections: ReviewFileSection[] = [];
  let current: { path: string; headerPath: string; lines: string[]; binary: boolean } | null =
    null;

  const flush = (): void => {
    if (current) {
      sections.push({
        path: current.path || current.headerPath,
        diffText: current.lines.join('\n'),
        binary: current.binary,
      });
    }
    current = null;
  };

  for (const line of fullDiff.split('\n')) {
    if (line.startsWith('diff --git ')) {
      flush();
      const m = line.match(/^diff --git a\/(.+) b\/(.+)$/);
      current = { path: '', headerPath: m ? m[2] : '', lines: [line], binary: false };
      continue;
    }
    if (!current) continue;
    current.lines.push(line);
    if (line.startsWith('+++ b/')) {
      current.path = line.slice(6);
    } else if (line.startsWith('+++ /dev/null')) {
      current.path = current.headerPath;
    } else if (line.startsWith('Binary files ') || line.startsWith('GIT binary patch')) {
      current.binary = true;
    }
  }
  flush();
  return sections.filter((s) => s.path !== '');
}
