import { describe, expect, it } from 'vitest';

import {
  auditUseAtFileQueryGovernance,
  formatAtFileQueryJson,
  useAtFileQuery,
} from '../useAtFileQuery';

describe('useAtFileQuery Phase P161 governance audit', () => {
  it('audits useAtFileQuery governance metadata with explicit session and archetype', () => {
    const audit = auditUseAtFileQueryGovernance('sess-p161', 'software-engineering');
    expect(audit.phase).toBe('P161');
    expect(audit.module).toBe('src/features/chat/useAtFileQuery.ts');
    expect(audit.sessionId).toBe('sess-p161');
    expect(audit.archetype).toBe('software-engineering');
    expect(audit.healthy).toBe(true);
    expect(audit.summaryMarkdown).toContain('P161 UseAtFileQuery Governance');
  });

  it('preserves @file query extraction and JSON formatting', () => {
    const res = useAtFileQuery('check @src/App.tsx', 18);
    expect(res.query).toBe('src/App.tsx');
    expect(formatAtFileQueryJson(res)).toContain('src/App.tsx');
    const fallback = auditUseAtFileQueryGovernance('   ', '   ');
    expect(fallback.sessionId).toBe('default');
  });
});
