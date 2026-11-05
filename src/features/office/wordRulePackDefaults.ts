/**
 * Built-in rule-pack fallbacks shared by DocumentAuditPanel (M2c) and
 * WordBatchAuditPanel (M5c). Used when listWordRulePacks fails or returns
 * empty, so both panels stay usable offline.
 */

import type { WordRulePackSummary } from '../../shared/api/wordAuditTypes';

export const DEFAULT_PACKS: WordRulePackSummary[] = [
  {
    id: 'general-quality',
    name: 'Word 通用质量检查',
    version: '1.0',
    origin: 'builtin',
    rule_count: 6,
  },
  {
    id: 'gb-t-9704-general',
    name: '党政机关公文格式（GB/T 9704 通用参数）',
    version: '1.0',
    origin: 'builtin',
    rule_count: 5,
  },
];

export const DEFAULT_PACK_ID = 'general-quality';
