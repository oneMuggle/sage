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
<<<<<<< HEAD
});

describe('endpointReadiness governance audit helpers (Phase P106)', () => {
=======
  it('treats a backend-saved key (hasApiKey) as configured without local text', () => {
    expect(
      isEndpointConfigured({
        baseUrl: 'https://api.example.com',
        apiKey: '',
        protocol: 'openai-compatible',
        hasApiKey: true,
      }),
    ).toBe(true);
    // Without baseUrl the endpoint is still unusable.
    expect(
      isEndpointConfigured({
        baseUrl: ' ',
        apiKey: '',
        protocol: 'openai-compatible',
        hasApiKey: true,
      }),
    ).toBe(false);
    // Redaction flag must not be trusted for a non-boolean.
    expect(
      isEndpointConfigured({
        baseUrl: 'https://api.example.com',
        apiKey: '',
        protocol: 'openai-compatible',
        hasApiKey: false,
      }),
    ).toBe(false);
  });
});

describe('endpointReadiness governance audit helpers (Phase P106)', () => {
  it('reflects backend-saved keys in the audit snapshot', () => {
    const snap = buildEndpointReadinessAuditSnapshot({
      baseUrl: 'https://api.example.com',
      apiKey: '',
      protocol: 'openai-compatible',
      hasApiKey: true,
    });
    expect(snap.configured).toBe(true);
    expect(snap.hasApiKey).toBe(true);
    expect(snap.signature).toBe('1|openai-compatible|1|1|1');
  });

>>>>>>> origin/main
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
