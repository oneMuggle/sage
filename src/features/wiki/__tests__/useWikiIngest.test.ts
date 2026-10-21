import { describe, expect, it } from 'vitest';

import { formatWikiIngestSummary, formatWikiIngestJson } from '../useWikiIngest';

describe('useWikiIngest audit helpers', () => {
  it('formats wiki ingest progress summary and json', () => {
    const state = {
      progress: { stage: 'embedding', percent: 65, message: '向量化中' },
      done: false,
      error: null,
    };
    expect(formatWikiIngestSummary('ing-101', state)).toBe(
      'ingest=ing-101 · stage=embedding · percent=65% · done=false',
    );
    const parsed = JSON.parse(formatWikiIngestJson('ing-101', state));
    expect(parsed).toEqual({
      ingestId: 'ing-101',
      stage: 'embedding',
      percent: 65,
      done: false,
      error: null,
    });
  });

  it('handles nullish ingestId and idle state safely', () => {
    expect(formatWikiIngestSummary(null, null)).toBe(
      'ingest=none · stage=idle · percent=0% · done=false',
    );
    expect(JSON.parse(formatWikiIngestJson('', undefined)).ingestId).toBeNull();
  });
});
