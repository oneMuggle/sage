import { useCallback } from 'react';

import { useBtwState } from '../../entities/chat/btwState';
import { useChat } from '../send-message/useChat';

/**
 * /btw 命令 hook - 管理旁路提问的生命周期
 *
 * 提供 open/close 方法控制 BtwOverlay 显示
 * open 时会调用 useChat.askBtw 发起流式请求
 */
export function useBtwCommand() {
  const { askBtw } = useChat();
  const btwState = useBtwState();

  const open = useCallback(
    (question: string) => {
      useBtwState.getState().open(question);
      askBtw(question);
    },
    [askBtw],
  );

  const close = useCallback(() => {
    useBtwState.getState().close();
  }, []);

  return {
    isOpen: btwState.isOpen,
    question: btwState.question,
    answer: btwState.answer,
    isLoading: btwState.isLoading,
    open,
    close,
  };
}
