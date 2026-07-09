// Wiki Chat - ask questions and get synthesized answers (with streaming)
import { Send, BookOpen } from 'lucide-react';
import { useEffect, useState } from 'react';

import { resolveEndpoint } from '../../entities/setting/types';
import { useWikiStore } from '../../entities/wiki/store';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useWikiChatStream } from '../../features/wiki/useWikiChatStream';
import { wikiChatStream } from '../../shared/api-client/wiki';

/** Default embedding model when the chat endpoint doubles as the embed endpoint.
 * Override via the embedding model setting in chat settings (future #3 followup). */
const DEFAULT_EMBED_MODEL = 'text-embedding-3-small';

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
  const [streamId, setStreamId] = useState<string | null>(null);
  // PR-2 follow-up: track the most recent completed query so we can show
  // a "no results" message when retrieval returns 0 pages.
  const [lastQueryHadNoResults, setLastQueryHadNoResults] = useState(false);
  const stream = useWikiChatStream(streamId);

  // PR-2 Task 5: the hook (`useWikiChatStream`) owns the per-stream
  // listeners and flips `stream.streaming` to false on done/error. Mirror
  // that into the local `loading` flag so the "正在思考..." placeholder
  // goes away when the stream ends — we no longer have a try/finally around
  // a single await because the streaming response resolves immediately.
  //
  // Dep is `[stream.streaming]` only — NOT `streamId` or `stream.error` —
  // because on the render where streamId just changed, the hook's own
  // useEffect has not yet executed its `setState({streaming: true})`, so
  // a dep of `[streamId, stream.streaming]` would observe the stale
  // streaming=false value and prematurely clear `loading`. Hook transitions
  // streaming: false → true (subscribed) → false (done/error); watching
  // the false→true→false toggles naturally skips the initial-false render.
  useEffect(() => {
    if (!stream.streaming) {
      // Hook finished streaming (done or error event fired).
      setLoading(false);
      // No-results UX: when the stream ends with no answer and no error,
      // and we had a recent query, surface "no results" so the user isn't
      // left staring at the empty-state placeholder.
      if (!stream.answer && !stream.error && messages.length > 0) {
        setLastQueryHadNoResults(true);
      }
    }
  }, [stream.streaming, stream.answer, stream.error, messages.length]);

  const chatEndpoint = resolveEndpoint(
    settings.settings.modelSelections.chatModel,
    settings.settings.endpoints,
  );
  const chatModelId = settings.settings.modelSelections.chatModel.modelId;

  const handleSend = async () => {
    if (!project || !input.trim() || !chatEndpoint || !chatModelId) return;

    const userMessage: ChatMessage = { role: 'user', content: input.trim() };
    setMessages((prev) => [...prev, userMessage]);
    const query = input.trim();
    setInput('');
    setLoading(true);

    try {
      // `wikiChatStream` is invoke-only — it does NOT subscribe to the
      // per-stream channels. We hand the returned `streamId` straight to
      // the `useWikiChatStream` hook above so it builds
      // `wiki-chat-stream-{streamId}-chunk/done/error` listeners against
      // the same id the Electron main relay is publishing to.
      const { streamId: serverStreamId } = await wikiChatStream({
        query,
        projectPath: project.path,
        llmBaseUrl: chatEndpoint.baseUrl,
        llmApiKey: chatEndpoint.apiKey,
        llmModel: chatModelId,
        embedBaseUrl: chatEndpoint.baseUrl, // 复用 chat 端点作为 embedding 端点(MVP)
        embedApiKey: chatEndpoint.apiKey,
        embedModel: DEFAULT_EMBED_MODEL,
      });
      setStreamId(serverStreamId);
    } catch (e) {
      setMessages((prev) => [...prev, { role: 'assistant', content: `查询失败: ${e}` }]);
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
        {messages.length === 0 && !stream.answer && !lastQueryHadNoResults && (
          <div className="flex flex-col items-center justify-center gap-2 text-muted text-sm py-12">
            <BookOpen className="h-8 w-8 text-muted/30" />
            <p>向你的 wiki 提问</p>
            <p className="text-xs">我会基于 wiki 中的内容回答你的问题</p>
          </div>
        )}

        {lastQueryHadNoResults && (
          <div className="flex justify-start" data-testid="chat-no-results">
            <div className="max-w-[80%] rounded-lg px-4 py-3 bg-bg-muted text-text">
              <div className="text-sm text-muted">未在 wiki 中找到相关内容</div>
            </div>
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

        {/* 流式累积中(还在 receiving chunks) */}
        {stream.answer && (
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-lg px-4 py-3 bg-bg-muted text-text">
              <div className="text-sm whitespace-pre-wrap">
                {stream.answer}
                {stream.streaming && (
                  <span className="inline-block w-1 h-3 ml-0.5 bg-primary animate-pulse" />
                )}
              </div>
              {stream.citations.length > 0 && (
                <div className="mt-2 pt-2 border-t border-border/30">
                  <div className="text-[11px] text-muted mb-1">引用:</div>
                  {stream.citations.map((cite: string, j: number) => (
                    <button
                      key={j}
                      onClick={() => handleCitationClick(cite)}
                      className="block text-xs text-primary hover:underline truncate w-full text-left"
                    >
                      {cite.split('/').pop()}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {stream.error && (
          <div className="flex justify-start">
            <div className="bg-red-500/10 text-red-400 rounded-lg px-4 py-3 text-sm">
              流式错误: {stream.error}
            </div>
          </div>
        )}

        {loading && !stream.answer && (
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
            disabled={loading || !chatEndpoint || !chatModelId}
            className="flex-1 rounded-md border border-border bg-bg-muted px-3 py-2 text-sm placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/20 text-text disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim() || !chatEndpoint || !chatModelId}
            className="px-3 py-2 bg-primary text-text-inverse rounded-md hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
