/**
 * textDiff — 字符级 diff（office-p1a）。
 *
 * Office 编辑预览 / 快照 diff 的 before→after 是 ~80 字符上下文片段，
 * 此前整段标红/标绿，看不出具体改了哪几个字。本模块用 LCS 算出字符级
 * 增删片段，供 DiffChangeRow 按 <del>/<ins> 分段染色。
 *
 * 护栏：单侧超过 MAX_DIFF_INPUT_CHARS 时退化为整段标记（DP 是 O(n²)，
 * 片段本来就有界，超限说明数据异常，不值得为之付出二次方代价）。
 */

export type DiffSpanKind = 'same' | 'add' | 'del';

export interface DiffSpan {
  text: string;
  kind: DiffSpanKind;
}

export interface DiffSide {
  before: DiffSpan[];
  after: DiffSpan[];
}

/** 单侧输入长度上限（超过退化为整段 del/add） */
export const MAX_DIFF_INPUT_CHARS = 300;

function pushSpan(list: DiffSpan[], kind: DiffSpanKind, text: string): void {
  if (!text) return;
  const last = list[list.length - 1];
  if (last && last.kind === kind) {
    last.text += text;
  } else {
    list.push({ text, kind });
  }
}

/**
 * Compute char-level diff spans for a before/after pair.
 * `before` spans only contain 'same'/'del'; `after` only 'same'/'add'.
 */
export function diffSpans(before: string, after: string): DiffSide {
  if (before === after) {
    const same = [{ text: before, kind: 'same' as const }];
    return { before: same, after: same.map((s) => ({ ...s })) };
  }
  if (before.length > MAX_DIFF_INPUT_CHARS || after.length > MAX_DIFF_INPUT_CHARS) {
    return {
      before: [{ text: before, kind: 'del' }],
      after: [{ text: after, kind: 'add' }],
    };
  }

  // 剥离公共前后缀，缩小 DP 规模
  let start = 0;
  const minLen = Math.min(before.length, after.length);
  while (start < minLen && before[start] === after[start]) start++;
  let endB = before.length;
  let endA = after.length;
  while (endB > start && endA > start && before[endB - 1] === after[endA - 1]) {
    endB--;
    endA--;
  }
  const midB = before.slice(start, endB);
  const midA = after.slice(start, endA);
  const m = midB.length;
  const n = midA.length;

  // LCS 长度表（自底向上；m,n ≤ 300 → ≤ 9 万格，Uint16 足够）
  const dp = new Uint16Array((m + 1) * (n + 1));
  const at = (i: number, j: number) => i * (n + 1) + j;
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[at(i, j)] =
        midB[i] === midA[j]
          ? dp[at(i + 1, j + 1)] + 1
          : Math.max(dp[at(i + 1, j)], dp[at(i, j + 1)]);
    }
  }

  const beforeSpans: DiffSpan[] = [];
  const afterSpans: DiffSpan[] = [];
  pushSpan(beforeSpans, 'same', before.slice(0, start));
  pushSpan(afterSpans, 'same', after.slice(0, start));

  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (midB[i] === midA[j]) {
      pushSpan(beforeSpans, 'same', midB[i]);
      pushSpan(afterSpans, 'same', midA[j]);
      i++;
      j++;
    } else if (dp[at(i + 1, j)] >= dp[at(i, j + 1)]) {
      pushSpan(beforeSpans, 'del', midB[i]);
      i++;
    } else {
      pushSpan(afterSpans, 'add', midA[j]);
      j++;
    }
  }
  while (i < m) {
    pushSpan(beforeSpans, 'del', midB[i]);
    i++;
  }
  while (j < n) {
    pushSpan(afterSpans, 'add', midA[j]);
    j++;
  }

  pushSpan(beforeSpans, 'same', before.slice(endB));
  pushSpan(afterSpans, 'same', after.slice(endA));
  return { before: beforeSpans, after: afterSpans };
}
