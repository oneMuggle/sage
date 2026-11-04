/**
 * 统一的时间格式化工具 (2026-11-03).
 *
 * 统一散落各组件的时间格式化实现, 全部使用浏览器本地时区 + zh-CN 区域,
 * 让日志/API/定时任务三处默认「本地时区, 失败回退北京时间」在前端渲染
 * 时也保持一致 —— 浏览器本身就是本地时区, 无需额外解析.
 *
 * 输入约定: 所有 ``ts`` 参数单位为**毫秒** (与 ``new Date(ts)`` 一致).
 * 若调用方持有秒级时间戳, 先乘 1000.
 */

const ZH_CN = 'zh-CN';

/**
 * 日期: "2026/11/03"
 *
 * 用于列表项、表格单元等仅显示日期的场景 (MemoryBrowser, ArchivesModal 等).
 */
export function formatDate(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return '—';
  try {
    return new Date(ts).toLocaleDateString(ZH_CN, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  } catch {
    return '—';
  }
}

/**
 * 日期 + 时间: "2026/11/03 14:23"
 *
 * 用于 tooltip、详情面板等需要精确到分钟的场景 (MemoryItem 等).
 */
export function formatDateTime(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return '—';
  try {
    return new Date(ts).toLocaleString(ZH_CN, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '—';
  }
}

/**
 * 仅时间 (24h): "14:23:45"
 *
 * 用于轨迹、事件时间线等只显示当日时刻的场景
 * (TrajectoryPane, EventTimeline).
 */
export function formatTimeOfDay(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return '';
  try {
    return new Date(ts).toLocaleTimeString(ZH_CN, {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return '';
  }
}

/**
 * 完整本地日期时间: "2026/11/03 14:23:45"
 *
 * 默认 ``toLocaleString('zh-CN')`` 的等价物, 用于进化日志、学习偏好、
 * 召回指标等旧版散落实现的统一替换.
 */
export function formatLocalString(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return String(ts);
  try {
    return new Date(ts).toLocaleString(ZH_CN);
  } catch {
    return String(ts);
  }
}

/**
 * 相对时间: "刚刚" / "X 分钟前" / "X 小时前" / "昨天 HH:MM" / "MM/DD".
 *
 * 用于对话气泡、消息列表等需要「距今多久」的场景 (TurnGroup 等).
 *
 * @param ts 毫秒时间戳
 */
export function formatRelativeTime(ts: number): string {
  if (!ts) return '';
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return '刚刚';
    if (diffMins < 60) return `${diffMins} 分钟前`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} 小时前`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays === 1) {
      return `昨天 ${date.toLocaleTimeString(ZH_CN, { hour12: false, hour: '2-digit', minute: '2-digit' })}`;
    }
    if (diffDays < 7) return `${diffDays} 天前`;
    return date.toLocaleDateString(ZH_CN, { month: '2-digit', day: '2-digit' });
  } catch {
    return '';
  }
}
