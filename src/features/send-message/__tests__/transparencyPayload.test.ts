/**
 * r103: transparencyPayload 校验器单测——三处消费共用的事件载荷契约。
 *
 * 契约口径：sources 非空数组且 kind 白名单；memories/skills/citations 允许
 * 空数组但元素必须有指定 string 字段；compact 三数字字段齐全。
 */
import { describe, expect, it } from 'vitest';

import {
  isValidCitationsPayload,
  isValidCompactPayload,
  isValidMemoriesPayload,
  isValidSkillsPayload,
  isValidSourcesPayload,
} from '../transparencyPayload';

describe('isValidSourcesPayload', () => {
  it('四种合法 kind 均通过', () => {
    expect(
      isValidSourcesPayload([
        { kind: 'web', title: 'a' },
        { kind: 'wiki', title: 'b' },
        { kind: 'tool', title: 'c' },
        { kind: 'memory', title: 'd' },
      ]),
    ).toBe(true);
  });

  it('空数组拒绝（sources 必须非空）', () => {
    expect(isValidSourcesPayload([])).toBe(false);
  });

  it('未知 kind / 缺 kind / null 项 / 非数组拒绝', () => {
    expect(isValidSourcesPayload([{ kind: 'social' }])).toBe(false);
    expect(isValidSourcesPayload([{ title: 'no kind' }])).toBe(false);
    expect(isValidSourcesPayload([null])).toBe(false);
    expect(isValidSourcesPayload('web')).toBe(false);
    expect(isValidSourcesPayload(undefined)).toBe(false);
  });
});

describe('isValidMemoriesPayload', () => {
  it('带 string id 的数组通过（空数组合法）', () => {
    expect(isValidMemoriesPayload([{ id: 'm1', preview: 'p' }])).toBe(true);
    expect(isValidMemoriesPayload([])).toBe(true);
  });

  it('缺 id / id 非字符串 / 项为 null / 非数组拒绝', () => {
    expect(isValidMemoriesPayload([{ preview: 'p' }])).toBe(false);
    expect(isValidMemoriesPayload([{ id: 42 }])).toBe(false);
    expect(isValidMemoriesPayload([null])).toBe(false);
    expect(isValidMemoriesPayload({ id: 'm1' })).toBe(false);
  });
});

describe('isValidSkillsPayload', () => {
  it('带 string name 的数组通过', () => {
    expect(isValidSkillsPayload([{ name: 'pdf_export', triggers_matched: ['导出'] }])).toBe(true);
    expect(isValidSkillsPayload([])).toBe(true);
  });

  it('缺 name / name 非字符串拒绝', () => {
    expect(isValidSkillsPayload([{ triggers_matched: [] }])).toBe(false);
    expect(isValidSkillsPayload([{ name: 7 }])).toBe(false);
  });
});

describe('isValidCitationsPayload', () => {
  it('带 string media_id 的数组通过', () => {
    expect(isValidCitationsPayload([{ media_id: 'med-1', score: 0.9 }])).toBe(true);
    expect(isValidCitationsPayload([])).toBe(true);
  });

  it('缺 media_id / media_id 非字符串拒绝', () => {
    expect(isValidCitationsPayload([{ score: 0.9 }])).toBe(false);
    expect(isValidCitationsPayload([{ media_id: 12 }])).toBe(false);
  });
});

describe('isValidCompactPayload', () => {
  it('三数字字段齐全通过', () => {
    expect(isValidCompactPayload({ before: 10, after: 4, removed: 6 })).toBe(true);
  });

  it('缺字段 / 非数字 / null / 数组拒绝', () => {
    expect(isValidCompactPayload({ before: 10, after: 4 })).toBe(false);
    expect(isValidCompactPayload({ before: '10', after: 4, removed: 6 })).toBe(false);
    expect(isValidCompactPayload(null)).toBe(false);
    expect(isValidCompactPayload([10, 4, 6])).toBe(false);
  });
});
