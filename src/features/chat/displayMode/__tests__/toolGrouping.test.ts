import { describe, it, expect } from 'vitest';

import type { ToolCall } from '../../../../shared/lib/store';
import type { Artifact } from '../../../artifacts/artifactApi';
import { canGroupToolCalls, toolGroupSummary } from '../toolGrouping';

describe('canGroupToolCalls', () => {
  const makeToolCall = (name: string, overrides: Partial<ToolCall> = {}): ToolCall => ({
    id: `tc-${name}`,
    name,
    args: {},
    result: 'ok',
    ...overrides,
  });

  it('returns false when streaming', () => {
    const tools = [makeToolCall('read'), makeToolCall('write'), makeToolCall('bash')];
    expect(canGroupToolCalls(tools, true, 3, {})).toBe(false);
  });

  it('returns false when tool count < threshold', () => {
    const tools = [makeToolCall('read'), makeToolCall('write')];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(false);
  });

  it('returns true when tool count >= threshold and no special tools', () => {
    const tools = [makeToolCall('read'), makeToolCall('write'), makeToolCall('bash')];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(true);
  });

  it('returns false when any tool has blockReason', () => {
    const tools = [
      makeToolCall('read'),
      makeToolCall('write'),
      makeToolCall('web_access', { metadata: { blockReason: 'blocked' } }),
    ];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(false);
  });

  it('returns false when any tool has imageData', () => {
    const tools = [
      makeToolCall('read'),
      makeToolCall('write'),
      makeToolCall('diagram', { metadata: { imageData: 'data:image/png;base64,...' } }),
    ];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(false);
  });

  it('returns false when any tool has mediaRefs', () => {
    const tools = [
      makeToolCall('read'),
      makeToolCall('write'),
      makeToolCall('media', {
        metadata: { mediaRefs: [{ id: 'm1', kind: 'image', mime_type: 'image/png' }] },
      }),
    ];
    expect(canGroupToolCalls(tools, false, 3, {})).toBe(false);
  });

  it('returns false when any tool has artifacts', () => {
    const tools = [
      makeToolCall('read'),
      makeToolCall('write'),
      makeToolCall('code', { id: 'tc-code' }),
    ];
    const artifact: Artifact = {
      id: 'a1',
      session_id: 'sess-1',
      tool_call_id: 'tc-code',
      path: '/tmp/a1',
      name: 'a1',
      kind: 'code',
      size: 0,
      created_at: 0,
    };
    const artifacts = { 'tc-code': [artifact] };
    expect(canGroupToolCalls(tools, false, 3, artifacts)).toBe(false);
  });

  it('returns true with threshold=1 in result mode', () => {
    const tools = [makeToolCall('read')];
    expect(canGroupToolCalls(tools, false, 1, {})).toBe(true);
  });
});

describe('toolGroupSummary', () => {
  it('returns empty string when cannot group', () => {
    expect(toolGroupSummary([], false)).toBe('');
  });

  it('summarizes tool counts', () => {
    const tools = [{ name: 'read' }, { name: 'write' }, { name: 'bash' }] as ToolCall[];
    expect(toolGroupSummary(tools, true)).toBe('read · write · bash');
  });

  it('shows count for repeated tools', () => {
    const tools = [{ name: 'read' }, { name: 'read' }, { name: 'write' }] as ToolCall[];
    expect(toolGroupSummary(tools, true)).toBe('read×2 · write');
  });
});
