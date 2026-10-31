/**
 * Safe HTMLMediaElement.play wrapper.
 *
 * jsdom does not implement play() and some Electron/OS combinations reject
 * it (autoplay policy, missing codec). Playback is best-effort; never let it
 * throw out of a React effect.
 */

export function safePlay(video: HTMLVideoElement): void {
  try {
    const result = video.play() as Promise<void> | undefined;
    if (result && typeof result.catch === 'function') {
      void result.catch(() => undefined);
    }
  } catch {
    // Ignore autoplay/codec errors; the poster/first frame remains visible.
  }
}
