import { describe, expect, it } from 'vitest';

import {
  buildEndpointReadinessAuditJson,
  buildEndpointReadinessAuditSnapshot,
  isEndpointConfigured,
} from '../endpointReadiness';

describe('protocol-aware endpoint readiness', () => {
  it('allows local Ollama without a key', () => {
    expect(
      isEndpointConfigured({ baseUrl: 'http://localhost:11434', apiKey: '', protocol: 'ollama' }),
    ).toBe(true);
  });
  it('requires a usable cloud key and URL', () => {
    expect(
      isEndpointConfigured({
        baseUrl: 'https://api.example.com',
        apiKey: ' ',
        protocol: 'openai-compatible',
      }),
    ).toBe(false);
    expect(isEndpointConfigured({ baseUrl: ' ', apiKey: 'key', protocol: 'anthropic' })).toBe(
      false,
    );
    expect(isEndpointConfigured(null)).toBe(false);
    expect(
      isEndpointConfigured({
        baseUrl: 'https://api.example.com',
        apiKey: 'key',
        protocol: 'anthropic',
      }),
    ).toBe(true);
  });
});

describe('endpointReadiness governance audit helpers (Phase P106)', () => {
  it('builds deterministic audit snapshot and JSON for null, ollama, and cloud endpoints', () => {
    const emptySnap = buildEndpointReadinessAuditSnapshot(null);
    expect(emptySnap).toEqual({
      configured: false,
      protocol: null,
      hasBaseUrl: false,
      hasApiKey: false,
      requiresApiKey: true,
      signature: '0|-|0|0|1',
    });

    const ollamaSnap = buildEndpointReadinessAuditSnapshot({
      baseUrl: 'http://localhost:11434',
      apiKey: '',
      protocol: 'ollama',
    });
    expect(ollamaSnap).toEqual({
      configured: true,
      protocol: 'ollama',
      hasBaseUrl: true,
      hasApiKey: false,
      requiresApiKey: false,
      signature: '1|ollama|1|0|0',
    });
    expect(
      JSON.parse(
        buildEndpointReadinessAuditJson({
          baseUrl: 'http://localhost:11434',
          apiKey: '',
          protocol: 'ollama',
        }),
      ),
    ).toEqual(ollamaSnap);
  });
});
