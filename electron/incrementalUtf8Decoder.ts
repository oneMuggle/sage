/**
 * Stream-friendly UTF-8 decoder for child-process pipes.
 *
 * Background: a multi-byte UTF-8 character (e.g. an emoji arriving as
 * `F0 9F 98 83`) may be split across two `data` events from Node's child
 * process stdout (`F0 9F` then `98 83`). The browser-native
 * `TextDecoder.decode(buffer)` with no `stream` flag would either:
 *   (a) silently substitute replacement chars (`U+FFFD`), or
 *   (b) throw under `fatal: true`.
 * Neither is acceptable for backend logs we want to surface verbatim.
 *
 * Solution: keep one TextDecoder per stream with `stream: true` so it
 * buffers incomplete sequences internally. The decoder is reused across
 * chunks; on stream end (`close()`) any trailing incomplete sequence is
 * surfaced via the escaped-byte fallback so we never lose information.
 *
 * Why `fatal: true` + a hex escape fallback (not `fatal: false`):
 *   - `fatal: true` keeps stdout "clean UTF-8 only" — corrupted bytes do
 *     NOT silently become `U+FFFD` which would be confused for a real
 *     character in renderer banners.
 *   - The fallback preserves the raw byte sequence for diagnosis in NDJSON
 *     logs (matches the legacy one-shot decoder behavior).
 *
 * Used by:
 *   - electron/main.ts: spawnBackend() stdout/stderr handlers
 *   - electron/doctor.ts: runDoctorCheck() stdout/stderr handlers
 */
export interface IncrementalUtf8Decoder {
  /**
   * Decode a chunk. Returns the longest valid UTF-8 suffix; any incomplete
   * trailing sequence is buffered internally for the next call.
   */
  push(value: Buffer | Uint8Array): string;
  /**
   * Flush any buffered incomplete sequence (call when the stream closes).
   * Returns the escaped-byte fallback for any trailing partial bytes.
   */
  close(): string;
  /** Reset the buffer; e.g. when the child process restarts. */
  reset(): void;
}

/**
 * Build a new incremental decoder. `escapeByte` is invoked for any bytes that
 * cannot be parsed as UTF-8 (invalid sequence) — defaults to a hex escape
 * matching the legacy one-shot decoder behavior.
 */
export function createIncrementalUtf8Decoder(
  escapeByte: (byte: number) => string = defaultEscapeByte,
): IncrementalUtf8Decoder {
  // `stream: true` is part of the WHATWG TextDecoderOptions spec and
  // supported at runtime by Node 16+; the lib.dom TextDecoderOptions
  // declaration in @types/node v22 doesn't include it yet, so we cast.
  let decoder = new TextDecoder('utf-8', {
    fatal: true,
    stream: true,
  } as TextDecoderOptions);
  return {
    push(value) {
      try {
        return decoder.decode(value, { stream: true } as TextDecodeOptions);
      } catch {
        // Should not happen with stream:true (it just buffers incomplete
        // bytes), but defend against any edge case: drop the bad chunk and
        // emit escaped bytes so the rest of the line stays readable.
        return Array.from(value).map((b) => escapeByte(b)).join('');
      }
    },
    close() {
      try {
        return decoder.decode();
      } catch {
        return '\\x<?incomplete>';
      }
    },
    reset() {
      // Discard any buffered partial bytes from a stale child process.
      decoder = new TextDecoder('utf-8', {
        fatal: true,
        stream: true,
      } as TextDecoderOptions);
    },
  };
}

function defaultEscapeByte(byte: number): string {
  return byte >= 0x20 && byte <= 0x7e
    ? String.fromCharCode(byte)
    : `\\x${byte.toString(16).padStart(2, '0')}`;
}