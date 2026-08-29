let demoModeOverride: boolean | undefined;

export function getDemoModeOverride(): boolean | undefined {
  return demoModeOverride;
}

export function setDemoModeOverride(value: boolean): void {
  demoModeOverride = value;
}
