/**
 * IPC client for ASR transcription (语音快速录入).
 *
 * asr_transcribe → POST /api/v1/asr/transcribe
 *   {audio_base64, format, language?} → {text}
 */
import { invoke } from './desktopInvoke';

export type AsrAudioFormat = 'webm' | 'wav' | 'ogg' | 'mp3' | 'm4a';

export interface AsrTranscribeResult {
  text: string;
}

export const asrClient = {
  async transcribe(
    audioBase64: string,
    format: AsrAudioFormat = 'webm',
    language?: string,
  ): Promise<AsrTranscribeResult> {
    return invoke<AsrTranscribeResult>('asr_transcribe', {
      audio_base64: audioBase64,
      format,
      ...(language ? { language } : {}),
    });
  },
};
