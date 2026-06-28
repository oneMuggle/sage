import { describe, expect, it } from 'vitest';

import { formatMessage } from '../formatMessage';

describe('formatMessage', () => {
  it('replaces single placeholder', () => {
    expect(formatMessage('Hello, {name}!', { name: 'Alice' })).toBe('Hello, Alice!');
  });

  it('replaces multiple placeholders', () => {
    expect(formatMessage('{greeting}, {name}!', { greeting: 'Hi', name: 'Bob' })).toBe('Hi, Bob!');
  });

  it('preserves placeholder literal when param missing', () => {
    expect(formatMessage('Hello, {name}!', {})).toBe('Hello, {name}!');
  });

  it('coerces number params to string', () => {
    expect(formatMessage('You have {count} messages', { count: 5 })).toBe('You have 5 messages');
  });

  it('returns empty string for null template', () => {
    expect(formatMessage(null, {})).toBe('');
  });

  it('returns empty string for undefined template', () => {
    expect(formatMessage(undefined, {})).toBe('');
  });

  it('returns template unchanged when no placeholders', () => {
    expect(formatMessage('Plain text', { unused: 'x' })).toBe('Plain text');
  });

  it('handles repeated placeholder', () => {
    expect(formatMessage('{x}-{x}', { x: 'A' })).toBe('A-A');
  });
});
