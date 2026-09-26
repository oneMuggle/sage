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
