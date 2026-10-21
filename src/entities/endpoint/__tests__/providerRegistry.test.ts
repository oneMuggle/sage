import { describe, expect, it } from 'vitest';

import {
  formatProviderRegistryJson,
  formatProviderRegistrySummary,
} from '../providerRegistry';

describe('providerRegistry audit helpers', () => {
  it('formats provider registry summary', () => {
    const summary = formatProviderRegistrySummary();
    expect(summary).toContain('providers=');
    expect(summary).toContain('openai-compatible');
    expect(summary).toContain('proxyBase=/api/v1/llm');
  });

  it('exports provider registry JSON snapshot', () => {
    const parsed = JSON.parse(formatProviderRegistryJson());
    expect(parsed.providerCount).toBeGreaterThanOrEqual(2);
    expect(parsed.ids).toContain('openai-compatible');
    expect(parsed.proxyBase).toBe('/api/v1/llm');
  });
});

