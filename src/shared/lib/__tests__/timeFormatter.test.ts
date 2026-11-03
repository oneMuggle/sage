import { describe, it, expect } from 'vitest';

import {
  formatDate,
  formatDateTime,
  formatTimeOfDay,
  formatLocalString,
  formatRelativeTime,
} from '../timeFormatter';

// 用本地墙钟构造时间戳, 避免测试结果随 CI 时区漂移.
const LOCAL_TS = new Date(2026, 10, 3, 14, 23, 45).getTime();

describe('timeFormatter', () => {
  describe('formatDate', () => {
    it('formats a positive ms timestamp as local date', () => {
      expect(formatDate(LOCAL_TS)).toBe('2026/11/03');
    });

    it('returns em dash for zero, negative and non-finite input', () => {
      expect(formatDate(0)).toBe('—');
      expect(formatDate(-1)).toBe('—');
      expect(formatDate(Number.NaN)).toBe('—');
      expect(formatDate(Number.POSITIVE_INFINITY)).toBe('—');
    });
  });

  describe('formatDateTime', () => {
    it('formats date and time to the minute', () => {
      expect(formatDateTime(LOCAL_TS)).toBe('2026/11/03 14:23');
    });

    it('returns em dash for invalid input', () => {
      expect(formatDateTime(0)).toBe('—');
      expect(formatDateTime(Number.NaN)).toBe('—');
    });
  });

  describe('formatTimeOfDay', () => {
    it('formats 24h time with seconds', () => {
      expect(formatTimeOfDay(LOCAL_TS)).toBe('14:23:45');
    });

    it('returns empty string for invalid input', () => {
      expect(formatTimeOfDay(0)).toBe('');
      expect(formatTimeOfDay(-5)).toBe('');
    });
  });

  describe('formatLocalString', () => {
    it('formats a full local date time', () => {
      const out = formatLocalString(LOCAL_TS);
      expect(out).toContain('2026');
      expect(out).toContain('14');
    });

    it('falls back to the raw value for invalid input', () => {
      expect(formatLocalString(0)).toBe('0');
      expect(formatLocalString(-12)).toBe('-12');
    });
  });

  describe('formatRelativeTime', () => {
    it('returns empty string for falsy input', () => {
      expect(formatRelativeTime(0)).toBe('');
    });

    it('returns 刚刚 for sub-minute differences', () => {
      expect(formatRelativeTime(Date.now() - 10_000)).toBe('刚刚');
    });

    it('returns minutes for sub-hour differences', () => {
      expect(formatRelativeTime(Date.now() - 5 * 60_000)).toBe('5 分钟前');
    });

    it('returns hours for sub-day differences', () => {
      expect(formatRelativeTime(Date.now() - 3 * 3_600_000)).toBe('3 小时前');
    });

    it('returns 昨天 for one-day differences', () => {
      expect(formatRelativeTime(Date.now() - 25 * 3_600_000)).toMatch(/^昨天 \d{2}:\d{2}$/);
    });

    it('returns day count within a week', () => {
      expect(formatRelativeTime(Date.now() - 3 * 86_400_000)).toBe('3 天前');
    });

    it('returns MM/DD beyond a week', () => {
      expect(formatRelativeTime(Date.now() - 10 * 86_400_000)).toMatch(/^\d{2}\/\d{2}$/);
    });
  });
});
