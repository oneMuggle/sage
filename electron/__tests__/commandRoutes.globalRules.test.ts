/**
 * global_rules_* IPC 路由断言（G1 / ~/.sage/SAGE.md）。
 *
 * 独立成文件而非塞进 commands.test.ts —— 后者有 architecture-baseline.json
 * 的行数基线（见 commands.sessionRules.test.ts 同款说明）。
 *
 * 安全要点：渲染进程只传内容，绝不传路径。body selector 必须剥掉任何
 * 越权字段（path/exists/...），否则后端 GlobalRulesUpdateRequest 会 422。
 */
import { describe, expect, it } from 'vitest';

import { COMMAND_ROUTES } from '../commands';

describe('global rules IPC routes (G1 ~/.sage/SAGE.md)', () => {
  it('has global_rules_get route: GET /api/v1/settings/global-rules', () => {
    const r = COMMAND_ROUTES.global_rules_get;
    expect(r).toBeDefined();
    expect(r.method).toBe('GET');
    expect(r.path({})).toBe('/api/v1/settings/global-rules');
    expect(r.body).toBeUndefined();
  });

  it('has global_rules_save route: PUT with content-only body', () => {
    const r = COMMAND_ROUTES.global_rules_save;
    expect(r).toBeDefined();
    expect(r.method).toBe('PUT');
    expect(r.path({})).toBe('/api/v1/settings/global-rules');
    expect(r.body!({ content: '# 规则\n', path: '/etc/passwd', exists: true })).toEqual({
      content: '# 规则\n',
    });
  });

  it('has global_rules_delete route: DELETE /api/v1/settings/global-rules', () => {
    const r = COMMAND_ROUTES.global_rules_delete;
    expect(r).toBeDefined();
    expect(r.method).toBe('DELETE');
    expect(r.path({})).toBe('/api/v1/settings/global-rules');
    expect(r.body).toBeUndefined();
  });

  it('has global_rules_templates route: GET /api/v1/settings/global-rules/templates', () => {
    const r = COMMAND_ROUTES.global_rules_templates;
    expect(r).toBeDefined();
    expect(r.method).toBe('GET');
    expect(r.path({})).toBe('/api/v1/settings/global-rules/templates');
    expect(r.body).toBeUndefined();
  });

  it('all global rules paths have /api/v1 prefix', () => {
    const paths = [
      COMMAND_ROUTES.global_rules_get.path({}),
      COMMAND_ROUTES.global_rules_save.path({}),
      COMMAND_ROUTES.global_rules_delete.path({}),
      COMMAND_ROUTES.global_rules_templates.path({}),
    ];
    paths.forEach((p) => expect(p).toMatch(/^\/api\/v1\//));
  });
});
