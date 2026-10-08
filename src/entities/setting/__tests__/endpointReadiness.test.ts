import { describe, expect, it } from 'vitest';

import { isEndpointConfigured } from '../endpointReadiness';

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
