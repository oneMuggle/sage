import { useEffect } from 'react'
import { useChat } from '../hooks/useChat'
import { useStore } from '../lib/store'
import { ChatInput } from '../components/chat/ChatInput'
import { MessageList } from '../components/chat/MessageList'
import { SessionList } from '../components/session/SessionList'

export function Chat() {
  const {
    messages,
    isLoading,
    sendMessage,
    interrupt,
    loadMessages,
  } = useChat()

  const {
    sessions,
    currentSessionId,
    setCurrentSessionId,
    createSession,
    deleteSession,
    loadSessions,
  } = useStore()

  // 初始加载会话列表
  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  // 当切换会话时加载消息
  useEffect(() => {
    if (currentSessionId) {
      loadMessages(currentSessionId)
    }
  }, [currentSessionId, loadMessages])

  const handleNewSession = async () => {
    const sessionId = await createSession()
    setCurrentSessionId(sessionId)
  }

  const handleSelectSession = (id: string) => {
    setCurrentSessionId(id)
  }

  const handleSendMessage = async (content: string) => {
    if (!currentSessionId) {
      await handleNewSession()
    }
    await sendMessage(content)
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* 左侧会话列表 */}
      <div className="w-72 border-r border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800">
        <SessionList
          sessions={sessions}
          currentSessionId={currentSessionId}
          onSelect={handleSelectSession}
          onNew={handleNewSession}
          onDelete={deleteSession}
        />
      </div>

      {/* 右侧聊天区域 */}
      <div className="flex-1 flex flex-col">
        {/* 消息列表 */}
        <div className="flex-1 overflow-y-auto">
          <MessageList messages={messages} />
        </div>

        {/* 输入框 */}
        <ChatInput
          onSend={handleSendMessage}
          onInterrupt={interrupt}
          isLoading={isLoading}
          disabled={!currentSessionId}
          placeholder={currentSessionId ? '输入消息...' : '先选择一个会话或创建新对话'}
        />
      </div>
    </div>
  )
}
