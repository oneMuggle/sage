import { describe, expect, it } from 'vitest';

import {
  langFromPath,
  formatFileLangSummary,
  formatFileLangJson,
} from '../fileLang';

describe('fileLang audit helpers', () => {
  it('resolves language from path and formats summary and json', () => {
    expect(langFromPath('src/pages/Chat.tsx')).toBe('typescript');
    expect(formatFileLangSummary('src/pages/Chat.tsx')).toBe(
      'path=src/pages/Chat.tsx · lang=typescript',
    );
    const parsed = JSON.parse(formatFileLangJson('src/pages/Chat.tsx'));
    expect(parsed).toEqual({
      path: 'src/pages/Chat.tsx',
      lang: 'typescript',
      recognized: true,
    });
  });

  it('falls back to plaintext for unknown or empty paths', () => {
    expect(formatFileLangSummary('README.unknown')).toBe('path=README.unknown · lang=plaintext');
    expect(formatFileLangSummary(null)).toBe('path=empty · lang=plaintext');
    expect(JSON.parse(formatFileLangJson('')).recognized).toBe(false);
  });
});
