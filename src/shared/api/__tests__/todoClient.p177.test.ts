import { describe, expect, it } from 'vitest';

import {
  auditTodoClientGovernance,
  formatTodoListJson,
  formatTodoListSummary,
} from '../todoClient';

describe('todoClient P177 governance audit', () => {
  it('audits todoClient governance contract and todo list formatters', () => {
    const raw = auditTodoClientGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.api.todo_client.governance.v1');
    expect(parsed.phase).toBe('P177');
    expect(parsed.methods).toContain('complete');
    const sample = { items: [], total: 0, limit: 20, offset: 0 };
    expect(formatTodoListSummary(sample)).toBe('0/0 todos · offset 0 · limit 20');
    expect(JSON.parse(formatTodoListJson(sample)).total).toBe(0);
  });
});
