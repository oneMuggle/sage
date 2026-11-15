import { describe, expect, it } from 'vitest';

import {
  formatWikiIngestSummary,
  formatWikiIngestJson,
  normalizeIngestProgress,
} from '../useWikiIngest';

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

describe('normalizeIngestProgress (2026-11-15 crash fix)', () => {
  it('keeps the new string-message contract and lifts code', () => {
    expect(
      normalizeIngestProgress({
        stage: 'failed',
        percent: 0,
        message: 'Wiki 导入失败（LLM 请求返回 HTTP 401）',
        code: 'wiki_ingest_failed',
      }),
    ).toEqual({
      stage: 'failed',
      percent: 0,
      message: 'Wiki 导入失败（LLM 请求返回 HTTP 401）',
      code: 'wiki_ingest_failed',
    });
  });

  it('unwraps legacy {code, message} object payloads into strings', () => {
    expect(
      normalizeIngestProgress({
        stage: 'failed',
        percent: 0,
        message: { code: 'wiki_ingest_failed', message: 'Wiki 导入失败' },
      }),
    ).toEqual({
      stage: 'failed',
      percent: 0,
      message: 'Wiki 导入失败',
      code: 'wiki_ingest_failed',
    });
  });

  it('falls back to code-only objects and sanitizes garbage payloads', () => {
    expect(
      normalizeIngestProgress({ stage: 'failed', message: { code: 'wiki_ingest_failed' } }),
    ).toEqual({ stage: 'failed', percent: 0, message: null, code: 'wiki_ingest_failed' });
    expect(normalizeIngestProgress(null)).toEqual({
      stage: 'unknown',
      percent: 0,
      message: null,
    });
    expect(normalizeIngestProgress({ stage: 42, percent: Number.NaN, message: [] })).toEqual({
      stage: 'unknown',
      percent: 0,
      message: null,
    });
  });
});
