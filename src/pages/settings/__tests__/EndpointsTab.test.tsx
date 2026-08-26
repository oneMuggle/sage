// @vitest-environment jsdom
/**
 * EndpointsTab cleanup contract (2026-08-26).
 *
 * Lock down two UX fixes from the validation session:
 *   1. Remove the localModelPath input — it had no inference consumer in
 *      the backend (LM Studio is consumed via OpenAI-compatible
 *      /v1/chat/completions with empty-key Authorization skipped). The
 *      field is still kept in storage types for backward-compat reads,
 *      but the regular endpoint form must not prompt users to fill it.
 *   2. Make the OpenAI-compatible protocol copy explicit about LM Studio
 *      + other OpenAI-shaped services. Plan §4: "将 UI 文案明确为
 *      OpenAI / LM Studio / 其他兼容服务；不新增重复 LM Studio provider."
 *
 * modelId stays as an advanced/optional fallback; ModelsTab's discovered
 * models + modelSelections is the normal selection path. If that ever
 * regresses, this file will not catch it — that's covered by ModelsTab's
 * own tests.
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS, type AppSettings } from '../../../entities/setting/types';
import { EndpointsTab } from '../EndpointsTab';
import type { EndpointsTabProps } from '../components';

// Stub the network-touching test connection so handleTest() never hits
// fetch / localhost during unit tests. The component itself doesn't fetch
// on mount, but importing the real module path pulls in optional chained
// env reads we don't need here.
vi.mock('../../../features/manage-endpoints/api', () => ({
  testEndpointConnection: vi.fn(async () => ({
    success: true,
    message: 'mocked',
    latency: 0,
    discoveredModels: [],
  })),
}));

function makeProps(overrides: Partial<AppSettings> = {}): EndpointsTabProps {
  const updateSettings = vi.fn();
  const settings: AppSettings = {
    ...DEFAULT_SETTINGS,
    endpoints: [
      {
        id: 'ep1',
        name: 'LM Studio',
        baseUrl: 'http://127.0.0.1:1234/v1',
        apiKey: '',
        protocol: 'openai-compatible',
        modelId: 'qwen2.5-7b-instruct',
        // localModelPath is still part of EndpointConfig (storage keeps it
        // for backward-compat reads per plan §4). It's only the UI input
        // that's being removed — the field stays a no-op for inference.
        localModelPath: '',
        discoveredModels: [],
        lastDiscoveredAt: 0,
      },
    ],
    ...overrides,
  };
  return { settings, updateSettings } as EndpointsTabProps;
}

describe('EndpointsTab (2026-08-26 cleanup)', () => {
  it('does NOT render a 本地模型路径 input in the regular endpoint edit form', () => {
    // Regression guard: Task 1 (2026-08-23) added this input together
    // with modelId, but it has no inference consumer. Removing it from
    // UI 2026-08-26; storage sanitizer still drops legacy values for
    // backward-compat reads, but the user must not be prompted to type
    // a local .gguf path any more.
    const props = makeProps();
    render(<EndpointsTab {...props} />);

    // Open the inline editor for the seeded endpoint.
    const editButton = screen.getByRole('button', { name: '编辑' });
    fireEvent.click(editButton);

    // The previous label was "本地模型路径 (Task 1 2026-08-23, 选填)".
    expect(screen.queryByText(/本地模型路径/)).toBeNull();
    expect(screen.queryByPlaceholderText(/\.gguf/)).toBeNull();
  });

  it('OpenAI-compatible protocol label explicitly mentions LM Studio + OpenAI', () => {
    // Plan §4: keep `openai-compatible` value (no separate LM Studio
    // provider) but make the UI copy explicit. Users on a localhost
    // OpenAI-shaped server (LM Studio, vLLM, llama.cpp /server, OAI proxy)
    // must see at least one of these names in the dropdown so they don't
    // think this option is reserved for the OpenAI cloud API.
    const props = makeProps();
    render(<EndpointsTab {...props} />);
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));

    const select = screen.getByTestId('endpoint-protocol-select');
    const optionTexts = Array.from((select as HTMLSelectElement).options).map((o) => o.text);
    const oaiOpt = optionTexts.find((t) => /OpenAI/.test(t));
    expect(oaiOpt).toBeDefined();
    // Regression guard: the previous label was just
    // "OpenAI 兼容 (/v1/chat/completions)" — no mention of LM Studio,
    // which made users look for a dedicated provider that doesn't exist.
    expect(oaiOpt!).toMatch(/LM Studio|兼容服务/);
  });

  it('protocol select still exposes all four protocols', () => {
    // Defensive: removing localModelPath must NOT accidentally shrink the
    // protocol dropdown. If any of ollama/anthropic/gemini disappears,
    // users on those endpoints lose the ability to switch protocols
    // from this tab.
    const props = makeProps();
    render(<EndpointsTab {...props} />);
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));

    const select = screen.getByTestId('endpoint-protocol-select');
    const values = within(select as HTMLElement)
      .getAllByRole('option')
      .map((o) => (o as HTMLOptionElement).value);
    expect(values).toEqual(
      expect.arrayContaining(['openai-compatible', 'ollama', 'anthropic', 'gemini']),
    );
  });

  it('API Key input keeps the LM Studio 留空 placeholder', () => {
    // Plan §2: empty API key is meaningful for local OpenAI-compatible
    // endpoints — the request layer skips Authorization when the key is
    // empty. The placeholder text is the cue for that.
    const props = makeProps();
    render(<EndpointsTab {...props} />);
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));

    const apiKeyInput = screen.getByPlaceholderText(/LM Studio 可留空/);
    expect(apiKeyInput).toBeInTheDocument();
    expect((apiKeyInput as HTMLInputElement).type).toBe('password');
  });

  it('Model ID input still renders as the advanced/optional fallback', () => {
    // Plan §4: modelId stays editable so power users can pin a specific
    // model when discovery is unreliable. ModelsTab's discoveredModels
    // + modelSelections is the normal selection path — if this input
    // disappears it breaks the fallback flow.
    const props = makeProps();
    render(<EndpointsTab {...props} />);
    fireEvent.click(screen.getByRole('button', { name: '编辑' }));

    expect(screen.getByPlaceholderText('留空走 ModelsTab 选择')).toBeInTheDocument();
  });
});
