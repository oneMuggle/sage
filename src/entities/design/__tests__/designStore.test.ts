import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as api from '../designApi';
import { useDesignStore } from '../designStore';

vi.mock('../designApi');

const baseProject = {
  id: 'p1',
  name: 'Demo',
  kind: 'deck' as const,
  system_id: 's',
  template_id: 't',
  brief: 'b',
  status: 'complete' as const,
  created_at: '2026-11-19T00:00:00Z',
  updated_at: '2026-11-19T00:00:00Z',
};

const sampleArtifact = {
  id: 'a1',
  project_id: 'p1',
  version: 1,
  html_content: '<html/>',
  title: 'v1',
  kind: 'html',
  export_formats: ['html'],
  source_prompt: '',
  created_at: '2026-11-19T00:00:00Z',
};

describe('designStore version + message state', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    useDesignStore.setState({
      currentProject: null,
      currentArtifact: null,
      previewArtifact: null,
      artifacts: [],
      messages: [],
      tweaks: {},
      loadingProject: false,
      errorProject: null,
    });
  });

  it('loadProject loads detail, messages and artifacts together', async () => {
    vi.mocked(api.getProject).mockResolvedValue({
      ...baseProject,
      latest_artifact: null,
    });
    vi.mocked(api.listMessages).mockResolvedValue([
      {
        id: 'm1',
        role: 'user',
        content: 'hi',
        created_at: '2026-11-19T00:00:00Z',
      },
    ]);
    vi.mocked(api.listArtifacts).mockResolvedValue([
      {
        id: 'a1',
        project_id: 'p1',
        version: 1,
        title: 'v1',
        kind: 'html',
        created_at: '2026-11-19T00:00:00Z',
      },
    ]);
    vi.mocked(api.getTweaks).mockResolvedValue({ accent: '#123456', radius: 8 });

    await useDesignStore.getState().loadProject('p1');

    expect(useDesignStore.getState().messages).toHaveLength(1);
    expect(useDesignStore.getState().artifacts[0].version).toBe(1);
    expect(useDesignStore.getState().tweaks).toEqual({
      accent: '#123456',
      radius: 8,
    });
    expect(useDesignStore.getState().loadingProject).toBe(false);
  });

  it('loadProject surfaces errors without clearing previous state', async () => {
    vi.mocked(api.getProject).mockRejectedValue(new Error('boom'));
    vi.mocked(api.listMessages).mockResolvedValue([]);
    vi.mocked(api.listArtifacts).mockResolvedValue([]);
    vi.mocked(api.getTweaks).mockResolvedValue({});

    await useDesignStore.getState().loadProject('p1');

    expect(useDesignStore.getState().errorProject).toBe('boom');
  });

  it('previewVersion fetches the full artifact into previewArtifact', async () => {
    vi.mocked(api.getArtifact).mockResolvedValue(sampleArtifact);

    await useDesignStore.getState().previewVersion('p1', 'a1');

    expect(useDesignStore.getState().previewArtifact?.version).toBe(1);
  });

  it('restoreVersion calls the API and clears the preview', async () => {
    vi.mocked(api.restoreArtifact).mockResolvedValue({
      ...sampleArtifact,
      id: 'a2',
      version: 2,
    });
    vi.mocked(api.getProject).mockResolvedValue({
      ...baseProject,
      latest_artifact: null,
    });
    vi.mocked(api.listMessages).mockResolvedValue([]);
    vi.mocked(api.listArtifacts).mockResolvedValue([]);
    vi.mocked(api.getTweaks).mockResolvedValue({});

    await useDesignStore.getState().restoreVersion('p1', 'a1');

    expect(api.restoreArtifact).toHaveBeenCalledWith('p1', 'a1');
    expect(useDesignStore.getState().previewArtifact).toBeNull();
  });

  it('clearPreview drops the preview artifact', () => {
    useDesignStore.setState({ previewArtifact: sampleArtifact });

    useDesignStore.getState().clearPreview();

    expect(useDesignStore.getState().previewArtifact).toBeNull();
  });

  it('generate polls generation progress while the request is in flight', async () => {
    vi.useFakeTimers();
    try {
      let resolveGenerate!: (artifact: typeof sampleArtifact) => void;
      vi.mocked(api.generateArtifact).mockImplementation(
        () => new Promise((resolve) => { resolveGenerate = resolve; }),
      );
      vi.mocked(api.getProgress).mockResolvedValue({
        stage: 'generating',
        message: 'Calling LLM',
      });
      vi.mocked(api.getProject).mockResolvedValue({
        ...baseProject,
        latest_artifact: null,
      });
      vi.mocked(api.listMessages).mockResolvedValue([]);
      vi.mocked(api.listArtifacts).mockResolvedValue([]);
      vi.mocked(api.getTweaks).mockResolvedValue({});

      const promise = useDesignStore.getState().generate('p1');
      expect(useDesignStore.getState().generationProgress?.stage).toBe('starting');

      await vi.advanceTimersByTimeAsync(800);
      expect(useDesignStore.getState().generationProgress?.stage).toBe('generating');

      resolveGenerate(sampleArtifact);
      await promise;
      expect(useDesignStore.getState().generationProgress).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
