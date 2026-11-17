/**
 * memoryTitle 推导工具测试（2026-11-17 记忆详情化）。
 */
import { describe, expect, it } from 'vitest';

import {
  MEMORY_PREVIEW_MAX,
  MEMORY_TITLE_MAX,
  countMemoryChars,
  deriveMemoryPreview,
  deriveMemoryTitle,
  resolveMemoryTitle,
} from '../memoryTitle';

describe('deriveMemoryTitle', () => {
  it('跳过前导空行，取首个非空行', () => {
    expect(deriveMemoryTitle('\n\n  用户偏好 TypeScript  ')).toBe('用户偏好 TypeScript');
  });

  it('去掉 markdown 标题/列表前缀', () => {
    expect(deriveMemoryTitle('## 项目约束说明')).toBe('项目约束说明');
    expect(deriveMemoryTitle('- 使用 pnpm 管理依赖')).toBe('使用 pnpm 管理依赖');
    expect(deriveMemoryTitle('1. 先做测试后写实现')).toBe('先做测试后写实现');
  });

  it('压缩连续空白', () => {
    expect(deriveMemoryTitle('用户   喜欢\t\tPython')).toBe('用户 喜欢 Python');
  });

  it('超长标题按上限截断并追加省略号', () => {
    const long = '长'.repeat(MEMORY_TITLE_MAX + 20);
    const title = deriveMemoryTitle(long);
    expect(title.length).toBeLessThanOrEqual(MEMORY_TITLE_MAX);
    expect(title.endsWith('…')).toBe(true);
  });

  it('空内容回退为"无标题"', () => {
    expect(deriveMemoryTitle('')).toBe('无标题');
    expect(deriveMemoryTitle(null)).toBe('无标题');
    expect(deriveMemoryTitle('   \n  ')).toBe('无标题');
  });
});

describe('resolveMemoryTitle', () => {
  it('优先使用后端 title 字段', () => {
    expect(resolveMemoryTitle({ title: '后端标题', content: '内容首行\n后续' })).toBe('后端标题');
  });

  it('后端 title 为空白时回退到内容推导', () => {
    expect(resolveMemoryTitle({ title: '   ', content: '内容首行' })).toBe('内容首行');
  });

  it('无 content 时回退 summary', () => {
    expect(resolveMemoryTitle({ summary: '摘要内容' })).toBe('摘要内容');
  });
});

describe('deriveMemoryPreview', () => {
  it('压缩空白后短内容原样返回', () => {
    expect(deriveMemoryPreview('短 内容\n第二行')).toBe('短 内容 第二行');
  });

  it('超长内容按预览上限截断', () => {
    const long = '预'.repeat(MEMORY_PREVIEW_MAX + 50);
    const preview = deriveMemoryPreview(long);
    expect(preview.length).toBe(MEMORY_PREVIEW_MAX + 1); // 上限 + 省略号
    expect(preview.endsWith('…')).toBe(true);
  });
});

describe('countMemoryChars', () => {
  it('统计原始字符数（含换行）', () => {
    expect(countMemoryChars('ab\ncd')).toBe(5);
    expect(countMemoryChars('')).toBe(0);
    expect(countMemoryChars(undefined)).toBe(0);
  });
});
