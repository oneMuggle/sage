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

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

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

  const handleSendMessage = async (content: string, _options?: {
    knowledgeRefs?: { id: string; title: string }[]
    attachments?: { name: string; size: number; type: string; dataUrl?: string }[]
    images?: { name: string; size: number; type: string; dataUrl?: string }[]
  }) => {
    if (!currentSessionId) {
      await handleNewSession()
    }
    await sendMessage(content)
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      <div className="w-72 border-r border-border bg-bg-muted">
        <SessionList
          sessions={sessions}
          currentSessionId={currentSessionId}
          onSelect={handleSelectSession}
          onNew={handleNewSession}
          onDelete={deleteSession}
        />
      </div>

      <div className="flex-1 flex flex-col">
        <div className="flex-1 overflow-y-auto">
          <MessageList messages={messages} />
        </div>

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
