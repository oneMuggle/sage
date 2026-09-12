// src/widgets/chat/changes/splitDiffParser.ts
//
// P1-3.8 (UI 优化方案 2026-09-13): 把 git 产出的 unified diff 解析为可被
// 分栏 (side-by-side) 视图消费的行列数据。纯函数,无副作用,可单测。
//
// 输入:
//   标准 unified diff (git diff / git diff --cached 输出格式),包括:
//   - 文件头 (diff --git / index / --- / +++)
//   - hunk 头 (@@ -L1,N1 +L2,N2 @@)
//   - 上下文行 (空格开头)
//   - 删除行 (- 开头)
//   - 新增行 (+ 开头)
//   - 尾部提示 ("\ No newline at end of file)
//
// 输出:
//   行对象列表,每行描述分栏视图里的一行:
//   - header:  跨列展示 (文件头 / hunk 头 / 元信息),两侧都不渲染
//   - context: 左右两侧同时显示相同文本(行号分别递增)
//   - modify:  成对的删除/新增,同行展示左右两侧内容
//   - remove:  仅左侧有内容
//   - add:     仅右侧有内容
//
// 配对逻辑:
//   一段连续的 -/+ 行视为一个修改组,按顺序一对一配对成 modify 行,
//   多余的 - 单独作 remove,多余的 + 单独作 add。这与 VSCode / GitHub
//   的分栏 diff 输出保持一致。

/** 一行分栏 diff 数据 */
export interface DiffRow {
  /** 行类型 */
  kind: 'header' | 'context' | 'modify' | 'add' | 'remove';
  /** 左侧行号 (原文件),header / add 行为 null */
  oldLine: number | null;
  /** 右侧行号 (新文件),header / remove 行为 null */
  newLine: number | null;
  /** 左侧文本 (空串表示该侧无内容) */
  oldText: string;
  /** 右侧文本 (空串表示该侧无内容) */
  newText: string;
}

/** 把 unified diff 解析成分栏行列表;空输入返回 [] */
export function parseUnifiedDiff(diff: string): DiffRow[] {
  if (!diff) return [];
  const rows: DiffRow[] = [];

  const rawLines = diff.split('\n');
  // 末尾空元素是 diff 末尾换行产生的,丢弃
  if (rawLines.length > 0 && rawLines[rawLines.length - 1] === '') rawLines.pop();

  let oldLine = 0;
  let newLine = 0;
  let inHunk = false;

  // 暂存一段连续的 -/+ 行,用于配对成 modify 行
  let pendingRemoves: Array<{ line: number; text: string }> = [];
  let pendingAdds: Array<{ line: number; text: string }> = [];

  const flushChanges = (): void => {
    const max = Math.max(pendingRemoves.length, pendingAdds.length);
    for (let i = 0; i < max; i++) {
      const r = pendingRemoves[i];
      const a = pendingAdds[i];
      if (r && a) {
        rows.push({
          kind: 'modify',
          oldLine: r.line,
          newLine: a.line,
          oldText: r.text,
          newText: a.text,
        });
      } else if (r) {
        rows.push({
          kind: 'remove',
          oldLine: r.line,
          newLine: null,
          oldText: r.text,
          newText: '',
        });
      } else if (a) {
        rows.push({
          kind: 'add',
          oldLine: null,
          newLine: a.line,
          oldText: '',
          newText: a.text,
        });
      }
    }
    pendingRemoves = [];
    pendingAdds = [];
  };

  const pushHeader = (text: string): void => {
    rows.push({ kind: 'header', oldLine: null, newLine: null, oldText: text, newText: text });
  };

  for (const rawLine of rawLines) {
    // ---- hunk 头:重置两侧行号 ----
    if (rawLine.startsWith('@@')) {
      flushChanges();
      const m = rawLine.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (m) {
        oldLine = parseInt(m[1], 10);
        newLine = parseInt(m[2], 10);
      }
      pushHeader(rawLine);
      inHunk = true;
      continue;
    }

    // ---- hunk 外:文件元信息 ----
    if (!inHunk) {
      if (
        rawLine.startsWith('diff ') ||
        rawLine.startsWith('---') ||
        rawLine.startsWith('+++') ||
        rawLine.startsWith('index ')
      ) {
        pushHeader(rawLine);
      }
      continue;
    }

    // ---- hunk 内 ----
    if (rawLine.startsWith(' ')) {
      // 上下文行:先 flush 未完成的修改组
      flushChanges();
      const text = rawLine.length > 0 ? rawLine.slice(1) : '';
      rows.push({
        kind: 'context',
        oldLine,
        newLine,
        oldText: text,
        newText: text,
      });
      oldLine++;
      newLine++;
    } else if (rawLine.startsWith('-')) {
      pendingRemoves.push({ line: oldLine, text: rawLine.slice(1) });
      oldLine++;
    } else if (rawLine.startsWith('+')) {
      pendingAdds.push({ line: newLine, text: rawLine.slice(1) });
      newLine++;
    } else if (rawLine.startsWith('\\')) {
      // "\ No newline at end of file" 等元信息
      flushChanges();
      pushHeader(rawLine);
    } else {
      // 其它未知行 (理论上不存在) 作为 header 兜底
      pushHeader(rawLine);
    }
  }

  flushChanges();
  return rows;
}
