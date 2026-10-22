/**
 * @vitest-environment jsdom
 */
import { describe, expect, it } from 'vitest';

import {
  defaultRecommendations,
  lucideIconMap,
  buildRecommendationsAuditJson,
  buildRecommendationsAuditSnapshot,
  type AssistantRecommendation,
} from '../recommendations';

describe('recommendations data', () => {
  it('exports the deliverable-oriented default recommendations', () => {
    expect(defaultRecommendations).toHaveLength(5);
  });

  it('every recommendation has all required fields and bilingual labels', () => {
    defaultRecommendations.forEach((rec: AssistantRecommendation) => {
      expect(rec.id).toBeTruthy();
      expect(rec.title).toBeTruthy();
      expect(rec.prompt).toBeTruthy();
      expect(rec.icon).toBeTruthy();
      expect(rec.gradient).toBeTruthy();
      expect(rec.labels?.zh.title).toBeTruthy();
      expect(rec.labels?.en.title).toBeTruthy();
    });
  });

  it('every icon name has a corresponding lucide icon component', () => {
    defaultRecommendations.forEach((rec) => {
      expect(lucideIconMap[rec.icon]).toBeDefined();
    });
  });

  it('default recommendations cover deliverables and keep a coding entry', () => {
    const ids = defaultRecommendations.map((r) => r.id);
    expect(ids).toContain('report');
    expect(ids).toContain('organize');
    expect(ids).toContain('data');
    expect(ids).toContain('slides');
    expect(ids).toContain('coding');
  });

  it('gradient is a background class string', () => {
    defaultRecommendations.forEach((rec) => {
      expect(rec.gradient).toMatch(/^bg-[a-z0-9-]+$/);
    });
  });
});

describe('recommendations governance audit helpers (Phase P106)', () => {
  it('builds deterministic audit snapshot and JSON for default and custom recommendations', () => {
    const defaultSnap = buildRecommendationsAuditSnapshot();
    expect(defaultSnap).toEqual({
      recommendationCount: 5,
      bilingualCount: 5,
      validIconCount: 5,
      ids: ['report', 'organize', 'data', 'slides', 'coding'],
      iconNames: ['FileText', 'FolderSearch', 'FileSpreadsheet', 'Presentation', 'Code2'],
      signature: '5|5|5|report,organize,data,slides,coding',
    });
    expect(JSON.parse(buildRecommendationsAuditJson())).toEqual(defaultSnap);
  });
});
