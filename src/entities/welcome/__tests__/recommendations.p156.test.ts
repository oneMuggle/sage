import { describe, expect, it } from 'vitest';

import {
  auditWelcomeRecommendationsGovernance,
  defaultRecommendations,
  lucideIconMap,
} from '../recommendations';

describe('welcome recommendations P156 governance audit', () => {
  it('returns healthy defaults for welcome recommendations governance', () => {
    const res = auditWelcomeRecommendationsGovernance();
    expect(res.module).toBe('src/entities/welcome/recommendations.ts');
    expect(res.phase).toBe('P156');
    expect(res.recommendationCount).toBe(defaultRecommendations.length);
    expect(res.iconCount).toBe(Object.keys(lucideIconMap).length);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when recommendationCount is 0', () => {
    const res = auditWelcomeRecommendationsGovernance({
      recommendationCount: 0,
      iconCount: 0,
    });
    expect(res.recommendationCount).toBe(0);
    expect(res.iconCount).toBe(0);
    expect(res.healthy).toBe(false);
  });
});
