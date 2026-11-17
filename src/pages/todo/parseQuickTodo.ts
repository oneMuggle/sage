/**
 * parseQuickTodo — 本地中文自然语言解析（纯规则，无网络/LLM 调用）。
 *
 * 支持：
 * - 日期：今天 / 明天 / 后天 / 大后天；周X / 星期X / 礼拜X（可带 下 / 本 / 这 前缀）；
 *   M月D日（已过则顺延到明年）
 * - 时间：HH点[MM分|半] / HH:MM / HH：MM，可带 上午 / 中午 / 下午 / 傍晚 / 晚上 / 凌晨
 * - 优先级：!高 / !中 / !低（也接受 !high / !medium / !low）
 * - 标签：#标签（可多个，空格分隔）
 *
 * 默认规则：
 * - 有日期无时间 → 当天 18:00
 * - 有时间无日期 → 今天该时刻；已过则明天该时刻
 * - 无修饰的整点（如「3点」）按字面小时理解，结合"今天已过则明天"规则
 *
 * 返回的 dueAt 为 naive 本地 ISO（YYYY-MM-DDTHH:mm:ss），与后端
 * `todos.due_at` 的存储约定一致（后端会把带时区的输入归一到 naive 本地）。
 */
import type { TodoPriority } from '../../shared/api/types';

export interface ParsedQuickTodo {
  title: string;
  dueAt?: string;
  priority?: TodoPriority;
  tags: string[];
}

const WEEKDAY_MAP: Record<string, number> = {
  一: 1,
  二: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  日: 0,
  天: 0,
  七: 0,
};

const RELATIVE_DAY_OFFSETS: Record<string, number> = {
  今天: 0,
  明天: 1,
  后天: 2,
  大后天: 3,
};

const MAX_TAGS = 10;
const MAX_TAG_LENGTH = 32;

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function toNaiveIso(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
}

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function addDays(d: Date, days: number): Date {
  const next = new Date(d);
  next.setDate(next.getDate() + days);
  return next;
}

function normalizeTags(tags: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of tags) {
    const tag = raw.trim().slice(0, MAX_TAG_LENGTH);
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    out.push(tag);
    if (out.length >= MAX_TAGS) break;
  }
  return out;
}

function parsePriorityToken(token: string): TodoPriority | undefined {
  const v = token.toLowerCase();
  if (v === '高' || v === 'high') return 'high';
  if (v === '低' || v === 'low') return 'low';
  if (v === '中' || v === 'medium') return 'medium';
  return undefined;
}

/** 有修饰词时把 12 小时制换算成 24 小时制。 */
function applyMeridiem(hour: number, modifier: string | undefined): number {
  if (!modifier) return hour;
  if (modifier === '下午' || modifier === '傍晚' || modifier === '晚上') {
    return hour < 12 ? hour + 12 : hour;
  }
  if (modifier === '中午') {
    return hour < 11 ? hour + 12 : hour;
  }
  if (modifier === '凌晨') {
    return hour === 12 ? 0 : hour;
  }
  if (modifier === '上午') {
    return hour === 12 ? 0 : hour;
  }
  return hour;
}

export function parseQuickTodo(input: string, now: Date = new Date()): ParsedQuickTodo {
  const original = input.trim();
  let text = original;
  const tags: string[] = [];
  let priority: TodoPriority | undefined;

  // 标签 #xxx
  text = text.replace(/#([^\s#]+)/g, (_m, tag: string) => {
    tags.push(tag);
    return ' ';
  });

  // 优先级 !高 / !high …
  text = text.replace(/!(高|中|低|high|medium|low)/gi, (_m, token: string) => {
    priority = priority ?? parsePriorityToken(token);
    return ' ';
  });

  let hasDate = false;
  let dateBase: Date | undefined;
  let hasTime = false;
  let hour = 0;
  let minute = 0;

  // 时间：HH点[MM分|半] / HH:MM / HH：MM（可带修饰词）
  const cnTime = text.match(
    /(凌晨|上午|中午|下午|傍晚|晚上)?\s*(\d{1,2})\s*[点时](半|\d{1,2})?分?/,
  );
  if (cnTime) {
    hasTime = true;
    hour = applyMeridiem(parseInt(cnTime[2], 10), cnTime[1]);
    if (cnTime[3] === '半') minute = 30;
    else if (cnTime[3]) minute = parseInt(cnTime[3], 10);
    text = text.replace(cnTime[0], ' ');
  } else {
    const colonTime = text.match(/(\d{1,2})[:：](\d{2})/);
    if (colonTime) {
      hasTime = true;
      hour = parseInt(colonTime[1], 10);
      minute = parseInt(colonTime[2], 10);
      text = text.replace(colonTime[0], ' ');
    }
  }

  // 日期：相对日
  const relative = text.match(/(大后天|后天|明天|今天)/);
  if (relative) {
    hasDate = true;
    dateBase = addDays(startOfDay(now), RELATIVE_DAY_OFFSETS[relative[1]]);
    text = text.replace(relative[0], ' ');
  } else {
    // 日期：周X / 星期X / 礼拜X（下 / 本 / 这 前缀）
    const weekday = text.match(/(下|本|这)?\s*(?:周|星期|礼拜)\s*([一二三四五六日天七])/);
    if (weekday) {
      hasDate = true;
      const target = WEEKDAY_MAP[weekday[2]];
      const today = startOfDay(now);
      const current = today.getDay();
      let diff = (target - current + 7) % 7;
      if (weekday[1] === '下') {
        // 下周一：下一个日历周的周一；恰好今天就是周一时取 +7
        diff = diff === 0 ? 7 : diff;
      } else if (weekday[1] === '本' || weekday[1] === '这') {
        // 本周X：按周一为周首直接定位（可能已过）
        const mondayBased = (d: number) => (d + 6) % 7;
        diff = mondayBased(target) - mondayBased(current);
      }
      dateBase = addDays(today, diff);
      text = text.replace(weekday[0], ' ');
    } else {
      // 日期：M月D日 / M月D号（已过则顺延明年）
      const monthDay = text.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]/);
      if (monthDay) {
        hasDate = true;
        const candidate = new Date(
          now.getFullYear(),
          parseInt(monthDay[1], 10) - 1,
          parseInt(monthDay[2], 10),
        );
        if (candidate.getTime() < startOfDay(now).getTime()) {
          candidate.setFullYear(candidate.getFullYear() + 1);
        }
        dateBase = candidate;
        text = text.replace(monthDay[0], ' ');
      }
    }
  }

  let dueAt: string | undefined;
  if (hasDate || hasTime) {
    const base = dateBase ?? startOfDay(now);
    if (hasTime) {
      const candidate = new Date(base.getFullYear(), base.getMonth(), base.getDate(), hour, minute);
      // 只有时间没有日期时：已过则明天。
      if (!hasDate && candidate.getTime() <= now.getTime()) {
        candidate.setDate(candidate.getDate() + 1);
      }
      dueAt = toNaiveIso(candidate);
    } else {
      // 只有日期：默认当天 18:00。
      dueAt = toNaiveIso(new Date(base.getFullYear(), base.getMonth(), base.getDate(), 18, 0));
    }
  }

  const title = text.replace(/\s+/g, ' ').trim() || original;

  return {
    title,
    dueAt,
    priority,
    tags: normalizeTags(tags),
  };
}
