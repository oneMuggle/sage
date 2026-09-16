/**
 * InlineMarks — Word read 输出的内联粗斜体标记渲染（office-p1a）。
 *
 * read_docx（backend/office/word.py）把 run 级 bold/italic 编码为
 * `**text**` / `*text*` markdown 标记，但预览端此前一直按字面纯文本
 * 呈现（用户会看到星号）。本组件解析这两类成对标记并渲染为
 * <strong>/<em>；配对残缺时按字面输出。纯文本节点 → React 文本，
 * 无注入面；不支持嵌套（后端编码器也不产出嵌套）。
 */
import type { ReactNode } from 'react';

const MARK_RE = /\*\*([^*]+)\*\*|\*([^*]+)\*/g;

export function renderInlineMarks(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  MARK_RE.lastIndex = 0;
  for (let m = MARK_RE.exec(text); m !== null; m = MARK_RE.exec(text)) {
    if (m.index > last) {
      nodes.push(text.slice(last, m.index));
    }
    if (m[1] !== undefined) {
      nodes.push(<strong key={`b${key++}`}>{m[1]}</strong>);
    } else if (m[2] !== undefined) {
      nodes.push(<em key={`i${key++}`}>{m[2]}</em>);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    nodes.push(text.slice(last));
  }
  return nodes;
}
