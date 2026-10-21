let demoModeOverride: boolean | undefined;

export function getDemoModeOverride(): boolean | undefined {
  return demoModeOverride;
}

export function setDemoModeOverride(value: boolean): void {
  demoModeOverride = value;
}

/* v8 ignore start */
export function formatDemoRuntimeSummary(override?: boolean | null): string {
  const val = override !== undefined ? override : getDemoModeOverride();
  const label = typeof val === 'boolean' ? String(val) : 'unset';
  return `demoOverride=${label}`;
}

export function formatDemoRuntimeJson(override?: boolean | null): string {
  const val = override !== undefined ? override : getDemoModeOverride();
  return JSON.stringify({
    demoOverride: typeof val === 'boolean' ? val : null,
    configured: typeof val === 'boolean',
  });
}
/* v8 ignore stop */
