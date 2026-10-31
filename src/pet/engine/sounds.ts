/**
 * Tiny WebAudio cues for waiting/error/done.
 *
 * No audio assets are shipped; tones are synthesized locally. Browsers may
 * keep the context suspended until a user gesture, so PetApp primes it on
 * pointer down and state-change sounds are best-effort.
 */

export type PetSoundKind = 'waiting' | 'error' | 'done';

let context: AudioContext | null = null;

function ensureContext(): AudioContext | null {
  try {
    if (!context) context = new AudioContext();
    if (context.state === 'suspended') void context.resume();
    return context;
  } catch {
    return null;
  }
}

export function primeAudio(): void {
  ensureContext();
}

function tone(
  ctx: AudioContext,
  frequency: number,
  startOffset: number,
  duration: number,
  type: OscillatorType = 'sine',
  volume = 0.045,
): void {
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  const start = ctx.currentTime + startOffset;
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(frequency, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(volume, start + 0.015);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(gain);
  gain.connect(ctx.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + 0.02);
}

export function playSound(kind: PetSoundKind): void {
  const ctx = ensureContext();
  if (!ctx) return;
  try {
    if (kind === 'waiting') {
      tone(ctx, 660, 0, 0.12);
      tone(ctx, 880, 0.14, 0.14);
      return;
    }
    if (kind === 'error') {
      tone(ctx, 240, 0, 0.22, 'square', 0.035);
      tone(ctx, 190, 0.24, 0.26, 'square', 0.03);
      return;
    }
    tone(ctx, 660, 0, 0.12);
    tone(ctx, 880, 0.12, 0.12);
    tone(ctx, 1320, 0.24, 0.2);
  } catch {
    // Audio is a nicety; never break the pet UI over it.
  }
}
