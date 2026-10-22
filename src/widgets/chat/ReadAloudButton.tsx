// 对话阅读体验 B1（docs/mcp-chat-reading-nav-optimization.md §10.4）：消息操作栏的
// 「朗读 / 停止朗读」按钮。环境不支持 speechSynthesis 时不渲染。
import { Square, Volume2 } from 'lucide-react';
import { useEffect } from 'react';

import { useReadAloudStore } from '../../features/chat/readAloudStore';
import { isSpeechSupported } from '../../features/chat/speech';
import { useI18n } from '../../shared/lib/i18n';

interface ReadAloudButtonProps {
  messageId: string;
  /** 消息 Markdown 原文 */
  content: string;
}

export function ReadAloudButton({ messageId, content }: ReadAloudButtonProps) {
  const { t } = useI18n();
  const speaking = useReadAloudStore((s) => s.speakingId === messageId);

  // 正在朗读的消息被卸载（切换会话、删除、离开聊天页）时停止朗读
  useEffect(
    () => () => {
      const store = useReadAloudStore.getState();
      if (store.speakingId === messageId) store.stop();
    },
    [messageId],
  );

  if (!isSpeechSupported()) return null;

  const label = speaking ? t('chat.read_aloud_stop') : t('chat.read_aloud');
  const toggle = () => {
    const store = useReadAloudStore.getState();
    if (speaking) store.stop();
    else store.speak(messageId, content, t('chat.read_aloud_code_omitted'));
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className={`p-1 rounded hover:bg-bg-hover ${speaking ? 'text-primary' : ''}`}
      title={label}
      aria-label={label}
      aria-pressed={speaking}
      data-testid="read-aloud-message"
    >
      {speaking ? <Square className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
    </button>
  );
}

export interface ReadAloudButtonAuditInput {
  textLength: number;
  speechSupported: boolean;
  isSpeaking: boolean;
  voiceAvailable: boolean;
}

export interface ReadAloudButtonAuditReport {
  textLength: number;
  speechSupported: boolean;
  isSpeaking: boolean;
  canSpeak: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateReadAloudButtonAudit(
  input: ReadAloudButtonAuditInput,
): ReadAloudButtonAuditReport {
  const textLength = Math.max(0, Math.trunc(input.textLength));
  const speechSupported = Boolean(input.speechSupported);
  const voiceAvailable = Boolean(input.voiceAvailable);
  const issueCodes: string[] = [];

  if (textLength === 0) {
    issueCodes.push('empty_read_aloud_text');
  }
  if (!speechSupported) {
    issueCodes.push('speech_synthesis_unsupported');
  }
  if (speechSupported && !voiceAvailable) {
    issueCodes.push('no_speech_voice_available');
  }

  const canSpeak = textLength > 0 && speechSupported && voiceAvailable;

  return {
    textLength,
    speechSupported,
    isSpeaking: Boolean(input.isSpeaking),
    canSpeak,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportReadAloudButtonAuditJson(
  input: ReadAloudButtonAuditInput,
): string {
  return JSON.stringify(evaluateReadAloudButtonAudit(input));
}
