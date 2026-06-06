// Wiki Chat - ask questions and get synthesized answers
import { Send, BookOpen } from 'lucide-react';
import { useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { wikiChat } from '../../lib/wiki-api';
import { useWikiStore } from '../../stores/wiki-store';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  citations?: string[];
}

export function WikiChat() {
  const project = useWikiStore((s) => s.project);
  const openFile = useWikiStore((s) => s.openFile);
  const setActiveView = useWikiStore((s) => s.setActiveView);
  const settings = useSettings();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const activeEp = settings.settings.endpoints.find((e) => e.isActive);
  const chatModel = settings.settings.modelSelections.chatModelId;

  const handleSend = async () => {
    if (!project || !input.trim() || !activeEp || !chatModel) return;

    const userMessage: ChatMessage = { role: 'user', content: input.trim() };
    setMessages((prev) => [...prev, userMessage]);
    const query = input.trim();
    setInput('');
    setLoading(true);

    try {
      const response = await wikiChat(
        query,
        project.path,
        activeEp.baseUrl,
        activeEp.apiKey,
        chatModel,
      );

      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: response.answer,
        citations: response.citations,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'assistant', content: `查询失败: ${e}` }]);
    } finally {
      setLoading(false);
    }
  };

  const handleCitationClick = (path: string) => {
    openFile(path);
    setActiveView('browser');
  };

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center text-muted text-sm">
        请先打开一个 wiki 项目
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Messages */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 text-muted text-sm py-12">
            <BookOpen className="h-8 w-8 text-muted/30" />
            <p>向你的 wiki 提问</p>
            <p className="text-xs">我会基于 wiki 中的内容回答你的问题</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[80%] rounded-lg px-4 py-3 ${
                msg.role === 'user' ? 'bg-primary text-text-inverse' : 'bg-bg-muted text-text'
              }`}
            >
              <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
              {msg.citations && msg.citations.length > 0 && (
                <div className="mt-2 pt-2 border-t border-border/30">
                  <div className="text-[11px] text-muted mb-1">引用:</div>
                  <div className="space-y-1">
                    {msg.citations.map((cite, j) => (
                      <button
                        key={j}
                        onClick={() => handleCitationClick(cite)}
                        className="block text-xs text-primary hover:underline truncate w-full text-left"
                      >
                        {cite.split('/').pop()}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-bg-muted rounded-lg px-4 py-3 text-sm text-muted">正在思考...</div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-border p-3 bg-surface">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="输入你的问题..."
            disabled={loading || !activeEp || !chatModel}
            className="flex-1 rounded-md border border-border bg-bg-muted px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/20 text-text disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim() || !activeEp || !chatModel}
            className="px-3 py-2 bg-primary text-text-inverse rounded-md hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
