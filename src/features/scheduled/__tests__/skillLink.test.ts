import { describe, expect, it } from 'vitest';

import type { Skill } from '../../../shared/api/types';
import {
  insertSkillRef,
  invalidRefLabels,
  parseSkillRefs,
  removeSkillRef,
  validateSkillRefs,
} from '../skillLink';

function skill(name: string, enabled = true): Skill {
  return {
    name,
    description: `${name} 的描述`,
    triggers: [],
    parameters: {},
    examples: [],
    enabled,
    usage_count: 0,
  } as Skill;
}

describe('scheduled/skillLink', () => {
  it('解析正文中的技能引用并去重', () => {
    expect(parseSkillRefs('/writer 帮我写报告')).toEqual(['writer']);
    expect(parseSkillRefs('先 /search 再 /writer，最后 /search')).toEqual(['search', 'writer']);
    expect(parseSkillRefs('路径 src/app.ts 不是技能')).toEqual([]);
    expect(parseSkillRefs('https://example.com/a/b 也不是技能')).toEqual([]);
  });

  it('按真实技能列表区分 已启用 / 已停用 / 未注册', () => {
    const refs = validateSkillRefs('用 /writer 和 /ghost，还有 /search', [
      skill('writer'),
      skill('search', false),
    ]);
    expect(refs.known).toEqual(['writer']);
    expect(refs.disabled).toEqual(['search']);
    expect(refs.unknown).toEqual(['ghost']);
    expect(invalidRefLabels(refs, '未注册', '已停用')).toEqual([
      '/ghost（未注册）',
      '/search（已停用）',
    ]);
  });

  it('技能列表不可用时不做“通过”判定', () => {
    const refs = validateSkillRefs('/writer', []);
    expect(refs.known).toEqual([]);
    expect(refs.unknown).toEqual(['writer']);
  });

  it('插入引用幂等，移除引用可恢复原文', () => {
    const once = insertSkillRef('每天汇总', 'writer');
    expect(once).toBe('每天汇总 /writer');
    expect(insertSkillRef(once, 'writer')).toBe(once);
    expect(removeSkillRef(once, 'writer')).toBe('每天汇总');
    expect(removeSkillRef('没有引用', 'writer')).toBe('没有引用');
  });

  it('空正文插入时不会留下多余空格', () => {
    expect(insertSkillRef('', 'writer')).toBe('/writer');
    expect(insertSkillRef('   ', 'writer')).toBe('/writer');
  });
});
