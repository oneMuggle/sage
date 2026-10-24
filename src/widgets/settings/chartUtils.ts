/**
 * SVG 路径工具 — 单调三次 Hermite 插值 (Fritsch-Carlson).
 *
 * 目的: 替换原先 "M x y L x y ..." 的直线段折线, 使趋势图视觉平滑,
 * 同时保证**不产生过冲** (曲线严格在相邻两点之间).
 *
 * 算法来源:
 *   F.N. Fritsch & R.E. Carlson (1980), "Monotone Piecewise Cubic Interpolation",
 *   SIAM J. Numer. Anal. 17(2), 238-246.
 * 与 D3 curveMonotoneX 同算法.
 *
 * 为什么不用 Catmull-Rom:
 *   Catmull-Rom 在某些段会过冲, 对"token 消耗 / cost"这种非负量会产生
 *   "视觉上为负"的错觉, 不可接受.
 *
 * 为什么不用 B-spline / 移动平均:
 *   B-spline 不经过原始数据点, 会让用户看到"假数据"; 移动平均引入相位延迟.
 */

interface Point {
  x: number;
  y: number;
}

/**
 * 单调三次插值生成 SVG path (open line, 不闭合).
 *
 * - 空数组 → ""
 * - 单点 → "M x y"
 * - 两点 → "M x0 y0 L x1 y1" (直线)
 * - 多点 → 三次 Bezier "M ... C ..."
 */
export function monotonePath(input: readonly Point[]): string {
  const n = input.length;
  if (n === 0) return '';
  if (n === 1) return `M ${input[0].x} ${input[0].y}`;
  if (n === 2) return `M ${input[0].x} ${input[0].y} L ${input[1].x} ${input[1].y}`;

  // Step 1: 计算每段差分 delta 与步长 h
  const delta: number[] = new Array(n - 1);
  const h: number[] = new Array(n - 1);
  for (let k = 0; k < n - 1; k++) {
    h[k] = input[k + 1].x - input[k].x;
    delta[k] = h[k] === 0 ? 0 : (input[k + 1].y - input[k].y) / h[k];
  }

  // Step 2: 初始化每个点的切线斜率 m
  const m: number[] = new Array(n);
  for (let k = 0; k < n; k++) {
    if (k === 0) {
      m[k] = delta[0];
    } else if (k === n - 1) {
      m[k] = delta[n - 2];
    } else {
      // 左右斜率的加权调和, 只在两侧同号时保留方向
      const left = delta[k - 1];
      const right = delta[k];
      if (left * right <= 0) {
        m[k] = 0;
      } else {
        const w1 = 2 * h[k] + h[k - 1];
        const w2 = h[k] + 2 * h[k - 1];
        m[k] =
          (w1 + w2) /
          (w1 / Math.max(Math.abs(left), 1e-12) + w2 / Math.max(Math.abs(right), 1e-12));
      }
    }
  }

  // Step 3: Fritsch-Carlson 单调性约束 (防过冲)
  for (let k = 0; k < n - 1; k++) {
    if (Math.abs(delta[k]) < 1e-12) {
      // 段水平 → 两端切线强制为 0
      m[k] = 0;
      m[k + 1] = 0;
    } else {
      const a = m[k] / delta[k];
      const b = m[k + 1] / delta[k];
      const s = a * a + b * b;
      if (s > 9) {
        const t = 3 / Math.sqrt(s);
        m[k] = t * a * delta[k];
        m[k + 1] = t * b * delta[k];
      }
    }
  }

  // Step 4: 构造 SVG path — 三次 Bezier "C" 命令
  const parts: string[] = [`M ${input[0].x} ${input[0].y}`];
  for (let k = 0; k < n - 1; k++) {
    const dx = h[k] / 3;
    const cp1x = input[k].x + dx;
    const cp1y = input[k].y + m[k] * dx;
    const cp2x = input[k + 1].x - dx;
    const cp2y = input[k + 1].y - m[k + 1] * dx;
    parts.push(`C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${input[k + 1].x} ${input[k + 1].y}`);
  }
  return parts.join(' ');
}

/**
 * 单调三次插值生成闭合 area path:
 * 上边沿走单调曲线, 下边沿沿 baseline (y=baselineY) 直连回去.
 *
 * 用于堆叠面积图 (UsageStatsTab).
 */
export function monotoneAreaPath(input: readonly Point[], baselineY: number): string {
  if (input.length === 0) return '';
  const top = monotonePath(input);
  const last = input[input.length - 1];
  const first = input[0];
  return `${top} L ${last.x} ${baselineY} L ${first.x} ${baselineY} Z`;
}
