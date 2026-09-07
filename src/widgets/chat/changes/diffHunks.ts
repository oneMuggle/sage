// src/widgets/chat/changes/diffHunks.ts
//
// U19 (对标增强第四轮批次 B): 前端 unified diff → hunk 块切分。
// 与 backend/office/workspace_revert.py:split_hunks 同构——hunk 序号
// (0-based) 两端一致，前端按序号勾选、后端按序号反向应用。
// 纯函数，可单测。

/** 单个 hunk：文件头（diff --git/index/---/+++）+ @@ 行与主体 */
export interface DiffHunk {
  header: string;
  body: string;
  /** @@ 行原文（不含换行），供 UI 概览展示 */
  summary: string;
}

/** 把 unified diff 切成带文件头的 hunk 列表；空 diff / 无 hunk → [] */
export function splitDiffHunks(diff: string): DiffHunk[] {
  const hunks: DiffHunk[] = [];
  let header = '';
  let current: { body: string[] } | null = null;

  const flush = (): void => {
    if (current && current.body.length > 0) {
      hunks.push({
        header,
        // @@ 行保留在 body 里——header + body 与后端 split_hunks 输出同构,
        // 可直接拼回原 hunk 段
        body: current.body.join(''),
        summary: current.body[0].trim(),
      });
    }
    current = null;
  };

  const lines = diff.split('\n');
  // 末尾换行产生的空元素只会在 hunk 体外多补一个换行,丢弃
  if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop();

  for (const line of lines) {
    const text = line + '\n';
    if (line.startsWith('diff --git')) {
      flush();
      header = text;
    } else if (line.startsWith('@@')) {
      flush();
      current = { body: [text] };
    } else if (current) {
      current.body.push(text);
    } else {
      header += text;
    }
  }
  flush();
  return hunks;
}
