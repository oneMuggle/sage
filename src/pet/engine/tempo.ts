/**
 * Idle pacing ranges, mirroring dsh-dafeiyu's quiet/standard/lively modes.
 * The pet plays one idle/random action, then rests for a random interval.
 */

const RANGES: Record<string, [number, number]> = {
  quiet: [45, 90],
  standard: [25, 45],
  lively: [12, 22],
};

export function idleDelayMs(tempo: string, random: () => number = Math.random): number {
  const [min, max] = RANGES[tempo] ?? RANGES.standard;
  return Math.round((min + random() * (max - min)) * 1000);
}
