import { describe, expect, it } from 'vitest';

import { formatGitStatusSummary, formatGitStatusJson } from '../gitStatusApi';

describe('gitStatusApi audit helpers', () => {
  it('formats git status response summary and json', () => {
    const status = {
      is_git_repo: true,
      branch: 'main',
      ahead: 2,
      behind: 1,
      files: [{ path: 'src/App.tsx', status: 'modified' as const }],
    };
    expect(formatGitStatusSummary(status)).toBe(
      'repo=true · branch=main · files=1 · ahead=2 · behind=1',
    );
    const parsed = JSON.parse(formatGitStatusJson(status));
    expect(parsed).toEqual({
      isGitRepo: true,
      branch: 'main',
      fileCount: 1,
      ahead: 2,
      behind: 1,
    });
  });

  it('handles non-repo or nullish status safely', () => {
    expect(formatGitStatusSummary(null)).toBe(
      'repo=false · branch=none · files=0 · ahead=0 · behind=0',
    );
    expect(JSON.parse(formatGitStatusJson(undefined)).isGitRepo).toBe(false);
  });
});
