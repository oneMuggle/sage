// src/shared/lib/unifiedDiff.ts
//
// right-panel R3 批次 A: 行级 unified diff 生成器（零依赖，纯函数）。
//
// 产出标准 unified diff（`---`/`+++` 头 + `@@ -a,s +b,t @@` hunk 头 +
// 空格/`-`/`+` 行），与 widgets/chat/changes/splitDiffParser 的输入约定
// 对齐，供版本对比视图复用 SplitDiff 渲染。
//
// 算法：经典 LCS 动态规划（O(N*M)）；行数乘积超过 MAX_DP_CELLS 时退化
// 为整文件替换，防内存尖峰。两文本相等返回空串。

/** hunk 头尾各保留的相等行数 */
const DEFAULT_CONTEXT = 3;
/** LCS 表规模上限（行数乘积） */
const MAX_DP_CELLS = 16_000_000;

export function unifiedDiff(
  oldText: string,
  newText: string,
  opts?: { oldLabel?: string; newLabel?: string; context?: number },
): string {
  const oldLabel = opts?.oldLabel ?? '旧版本';
  const newLabel = opts?.newLabel ?? '新版本';
  const ctx = opts?.context ?? DEFAULT_CONTEXT;

  if (oldText === newText) return '';

  const a = splitLines(oldText);
  const b = splitLines(newText);
  const ops = diffOps(a, b);
  if (ops.length === 0) return '';

  const out: string[] = [`--- ${oldLabel}`, `+++ ${newLabel}`];

  // 相邻变更间隔超过 2*ctx+1 行时拆分 hunk
  const groups = groupOps(ops, ctx);

  // bDelta = 截至当前 hunk 起点，b 行号相对 a 行号的偏移（累计 add - remove）
  let bDelta = 0;
  for (const g of groups) {
    const first = g[0];
    const last = g[g.length - 1];

    const aFrom = Math.max(0, first.aIndex - ctx);
    const aTo = Math.min(a.length, last.aIndex + (last.kind === 'remove' ? 1 : 0) + ctx);
    const bFrom = aFrom + bDelta;

    // 组内变更统计
    const removesAt = new Map<number, string[]>();
    const addsAt = new Map<number, string[]>();
    let removes = 0;
    let adds = 0;
    for (const op of g) {
      if (op.kind === 'remove') {
        const list = removesAt.get(op.aIndex) ?? [];
        list.push(op.text);
        removesAt.set(op.aIndex, list);
        removes++;
      } else {
        const list = addsAt.get(op.aIndex) ?? [];
        list.push(op.text);
        addsAt.set(op.aIndex, list);
        adds++;
      }
    }

    const aLen = aTo - aFrom;
    const bLen = aLen - removes + adds;
    const aHead = aLen === 0 ? aFrom : aFrom + 1;
    const bHead = bLen === 0 ? bFrom : bFrom + 1;
    out.push(`@@ -${aHead},${aLen} +${bHead},${bLen} @@`);

    // 回放 hunk body：逐 a 行输出，先该行上的 remove/add，再 context；
    // 已发射的 remove/add 立即从 map 删除，保证回放必然终止
    let ai = aFrom;
    while (ai <= aTo) {
      const removals = removesAt.get(ai);
      const insertions = addsAt.get(ai);
      let acted = false;
      if (removals) {
        for (const text of removals) out.push(`-${text}`);
        removesAt.delete(ai);
        ai++;
        acted = true;
      }
      if (insertions) {
        // 插入行位于 a[ai] 之前；ai 不前进，但键已删除不会重复
        for (const text of insertions) out.push(`+${text}`);
        addsAt.delete(ai);
        acted = true;
      }
      if (acted) continue;
      if (ai < aTo) {
        out.push(` ${a[ai]}`);
        ai++;
        continue;
      }
      break;
    }

    bDelta += adds - removes;
  }

  return out.join('\n');
}

// ---------- 内部实现 ----------

type Op =
  | { kind: 'remove'; aIndex: number; text: string }
  | { kind: 'add'; aIndex: number; text: string };

function splitLines(text: string): string[] {
  return text.length ? text.replace(/\n$/, '').split('\n') : [];
}

/** 按 a 位置间隔把变更切成 hunk 组 */
function groupOps(ops: Op[], ctx: number): Op[][] {
  const groups: Op[][] = [];
  let current: Op[] = [];
  let lastAIndex: number | null = null;
  for (const op of ops) {
    if (lastAIndex !== null && op.aIndex - lastAIndex > ctx * 2 + 1) {
      groups.push(current);
      current = [];
    }
    current.push(op);
    lastAIndex = op.aIndex;
  }
  if (current.length > 0) groups.push(current);
  return groups;
}

/** LCS diff：只产出 remove/add（按 a 序）；相等行隐含在 aIndex 间隔里 */
function diffOps(a: string[], b: string[]): Op[] {
  if (a.length * b.length > MAX_DP_CELLS) {
    return [
      ...a.map((text, aIndex) => ({ kind: 'remove' as const, aIndex, text })),
      ...b.map((text) => ({ kind: 'add' as const, aIndex: a.length, text })),
    ];
  }

  const m = a.length;
  const n = b.length;
  const dp: Uint32Array[] = Array.from({ length: m + 1 }, () => new Uint32Array(n + 1));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const ops: Op[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ kind: 'remove', aIndex: i, text: a[i] });
      i++;
    } else {
      ops.push({ kind: 'add', aIndex: i, text: b[j] });
      j++;
    }
  }
  while (i < m) {
    ops.push({ kind: 'remove', aIndex: i, text: a[i] });
    i++;
  }
  while (j < n) {
    ops.push({ kind: 'add', aIndex: i, text: b[j] });
    j++;
  }
  return ops;
}
