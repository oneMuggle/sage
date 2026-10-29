/**
 * 最近访问的 tab（P3）。
 *
 * 设置页有 17 个 tab，反复「记住位置」的成本不低：用户通常在 2–3 个 tab
 * 之间来回跳。把最近访问的少数几个 tab 固定在导航顶部，比逼用户每次在
 * 分组里重新找要省事。
 *
 * 持久化格式：localStorage 里的 JSON 字符串数组，元素必须是注册表里的
 * 合法 tab key。读取时整体校验并去重 —— 注册表删过 tab（`general`、
 * `memory-knowledge`），旧数据里残留的失效 key 必须被丢弃而不是渲染成
 * 一个点了没反应的死按钮。
 */

import { SETTINGS_TAB_KEYS, type SettingsTabKey } from './settingsTabs';

export const SETTINGS_RECENTS_STORAGE_KEY = 'sage:settings-recent-tabs';

/** 顶部「最近访问」最多展示几条 —— 再多就与下面完整分组重复了。 */
export const MAX_SETTINGS_RECENTS = 3;

function isSettingsTabKey(value: string): value is SettingsTabKey {
  return SETTINGS_TAB_KEYS.includes(value as SettingsTabKey);
}

/** 解析持久化值：非法 JSON / 非数组 / 失效 key 一律丢弃，保序去重。 */
export function sanitizeSettingsRecents(raw: string | null): SettingsTabKey[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const seen = new Set<SettingsTabKey>();
  for (const value of parsed) {
    if (typeof value !== 'string') continue;
    if (!isSettingsTabKey(value)) continue;
    seen.add(value);
  }
  return Array.from(seen).slice(0, MAX_SETTINGS_RECENTS);
}

/** 把 tab 提到最前；已存在则前移而不是重复。 */
export function pushSettingsRecent(
  current: readonly SettingsTabKey[],
  tab: SettingsTabKey,
): SettingsTabKey[] {
  return [tab, ...current.filter((key) => key !== tab)].slice(0, MAX_SETTINGS_RECENTS);
}

export function loadSettingsRecents(): SettingsTabKey[] {
  try {
    return sanitizeSettingsRecents(localStorage.getItem(SETTINGS_RECENTS_STORAGE_KEY));
  } catch {
    // localStorage 在隐私模式 / 配额耗尽下会抛 —— 最近访问只是便利功能，
    // 失败就退化成「没有最近访问」，不该拖垮整个设置页。
    return [];
  }
}

export function saveSettingsRecents(list: readonly SettingsTabKey[]): void {
  try {
    localStorage.setItem(SETTINGS_RECENTS_STORAGE_KEY, JSON.stringify(list));
  } catch {
    /* 同上：写不进去就算了 */
  }
}
