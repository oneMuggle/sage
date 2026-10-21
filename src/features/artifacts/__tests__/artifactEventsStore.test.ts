import { describe, expect, it } from 'vitest';

import {
  bumpArtifactEvent,
  formatArtifactEventsJson,
  formatArtifactEventsSummary,
  useArtifactEventsStore,
} from '../artifactEventsStore';

describe('artifactEventsStore audit helpers', () => {
  it('bumps session artifact counts and formats summary', () => {
    useArtifactEventsStore.setState({ counts: {} });
    bumpArtifactEvent('sess-1');
    bumpArtifactEvent('sess-1');
    const counts = useArtifactEventsStore.getState().counts;
    expect(formatArtifactEventsSummary(counts)).toBe(
      'sessions=1 · totalEvents=2',
    );
  });

  it('serializes artifact events audit JSON', () => {
    expect(
      JSON.parse(formatArtifactEventsJson({ 'sess-a': 3, 'sess-b': 1 })),
    ).toEqual({
      sessionCount: 2,
      totalEvents: 4,
      counts: { 'sess-a': 3, 'sess-b': 1 },
    });
  });
});
