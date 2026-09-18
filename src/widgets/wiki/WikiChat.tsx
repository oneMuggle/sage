import { Send, BookOpen } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { resolveEndpoint } from '../../entities/setting/types';
import { useWikiStore } from '../../entities/wiki/store';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useWikiChatStream } from '../../features/wiki/useWikiChatStream';
import {
  locateWikiCitation,
  type WikiChatStreamRequest,
  wikiListDirectory,
} from '../../shared/api-client/wiki';
import type { FileNode, WikiCitation, WikiCitationLocation } from '../../shared/types/wiki';

const MAX_SELECTED_SOURCES = 500;

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  citations?: WikiCitation[];
  sources?: WikiCitation[];
  error?: string | null;
}

function Citation({ citation, projectPath }: { citation: WikiCitation; projectPath: string }) {
  const openFile = useWikiStore((s) => s.openFile);
  const setActiveView = useWikiStore((s) => s.setActiveView);
  const [location, setLocation] = useState<WikiCitationLocation | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const locate = async () => {
    setExpanded(true);
    setLoading(true);
    setError('');
    setLocation(null);
    try {
      const result = await locateWikiCitation(projectPath, citation);
      if (alive.current) setLocation(result);
    } catch (cause) {
      if (alive.current) setError(`定位失败：${String(cause)}`);
    } finally {
      if (alive.current) setLoading(false);
    }
  };
  return (
    <div className="text-xs border-t border-border/30 pt-2">
      <button
        className="text-primary hover:underline text-left"
        title={citation.excerpt}
        aria-expanded={expanded}
        disabled={loading}
        onClick={() => void locate()}
      >
        [{citation.id}] {citation.title} · 第 {citation.line_start}–{citation.line_end} 行
      </button>
      {expanded && (
        <div className="mt-2 space-y-2">
          <p className="text-muted">生成回答时的证据</p>
          <pre className="whitespace-pre-wrap break-words">{citation.excerpt}</pre>
          {loading && <p role="status">正在核实原文…</p>}
          {error && <p role="alert">{error}</p>}
          {location?.changed && <p role="status">来源已变化，原位置可能失效，请打开文件核实。</p>}
          {location && !location.changed && (
            <pre
              aria-label="定位原文"
              className="whitespace-pre-wrap break-words bg-primary/10 p-2"
            >
              {location.excerpt}
            </pre>
          )}
          <button
            className="text-primary"
            onClick={() => {
              void openFile(citation.path);
              setActiveView('browser');
            }}
          >
            打开原文件
          </button>
        </div>
      )}
    </div>
  );
}

export function WikiChat() {
  const project = useWikiStore((s) => s.project);
  return project ? (
    <ProjectChat key={project.path} projectPath={project.path} />
  ) : (
    <div className="flex h-full items-center justify-center text-muted text-sm">
      请先打开一个 wiki 项目
    </div>
  );
}

function ProjectChat({ projectPath }: { projectPath: string }) {
  const settings = useSettings();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamId, setStreamId] = useState<string | null>(null);
  const [paths, setPaths] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [sourceError, setSourceError] = useState('');
  const [sourceLoading, setSourceLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [request, setRequest] = useState<WikiChatStreamRequest>();
  const pending = useRef(false);
  const stream = useWikiChatStream(streamId, request);
  useEffect(() => {
    let disposed = false;
    setSourceLoading(true);
    setSourceError('');
    const collect = (nodes: FileNode[]): string[] =>
      nodes
        .filter((node) => !node.name.startsWith('.'))
        .flatMap((node) =>
          node.is_dir
            ? collect(node.children ?? [])
            : node.path.startsWith('wiki/') &&
                node.name.endsWith('.md') &&
                !['index.md', 'log.md', 'schema.md'].includes(node.name)
              ? [node.path]
              : [],
        );
    wikiListDirectory('wiki', projectPath)
      .then(collect)
      .then((result) => {
        if (!disposed) {
          const unique = [...new Set(result)].sort();
          setPaths(unique);
          setSelected(unique.slice(0, MAX_SELECTED_SOURCES));
        }
      })
      .catch((cause: unknown) => {
        if (!disposed) setSourceError(`来源加载失败：${String(cause)}`);
      })
      .finally(() => {
        if (!disposed) setSourceLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [projectPath, reload]);
  useEffect(() => {
    if (!streamId || !stream.completed) return;
    setMessages((previous) => [
      ...previous,
      {
        role: 'assistant',
        content: stream.answer || (stream.error ? '' : '未在 wiki 中找到相关内容'),
        citations: stream.citations,
        sources: stream.sources,
        error: stream.error,
      },
    ]);
    setStreamId(null);
    pending.current = false;
    setLoading(false);
  }, [streamId, stream.completed, stream.answer, stream.citations, stream.sources, stream.error]);
  const endpoint = resolveEndpoint(
    settings.settings.modelSelections.chatModel,
    settings.settings.endpoints,
  );
  const model = settings.settings.modelSelections.chatModel.modelId;
  const canSend =
    !loading && !sourceLoading && !sourceError && selected.length > 0 && !!endpoint && !!model;
  const send = async () => {
    if (!canSend || !input.trim() || !endpoint || pending.current) return;
    pending.current = true;
    const query = input.trim();
    setMessages((previous) => [...previous, { role: 'user', content: query }]);
    setInput('');
    setLoading(true);
    setRequest({
      query,
      projectPath,
      selectedPaths: selected,
      llmBaseUrl: endpoint.baseUrl,
      llmApiKey: endpoint.apiKey,
      llmModel: model,
      embedBaseUrl: endpoint.baseUrl,
      embedApiKey: endpoint.apiKey,
      embedModel: 'text-embedding-3-small',
    });
    setStreamId(`wiki-chat-${crypto.randomUUID()}`);
  };
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <details className="border-b border-border p-3" open>
        <summary className="text-sm cursor-pointer">
          本次来源（{selected.length}/{paths.length}）
        </summary>
        {sourceLoading ? (
          <p role="status">正在加载来源…</p>
        ) : sourceError ? (
          <div role="alert">
            {sourceError}
            <button onClick={() => setReload((value) => value + 1)}>重试</button>
          </div>
        ) : (
          <>
            {paths.length > MAX_SELECTED_SOURCES && (
              <p role="status" className="text-xs text-muted">
                每次最多选择 500 个来源，默认及全选仅选择排序后的前 500 个，可取消后替换。
              </p>
            )}
            <div className="flex gap-3 my-2 text-xs">
              <button
                disabled={loading}
                onClick={() => setSelected(paths.slice(0, MAX_SELECTED_SOURCES))}
              >
                全选
              </button>
              <button disabled={loading} onClick={() => setSelected([])}>
                清空选择
              </button>
            </div>
            <div className="max-h-32 overflow-auto">
              {paths.map((path) => (
                <label key={path} className="flex gap-2 text-xs py-1">
                  <input
                    type="checkbox"
                    checked={selected.includes(path)}
                    disabled={
                      loading ||
                      (!selected.includes(path) && selected.length >= MAX_SELECTED_SOURCES)
                    }
                    onChange={(event) =>
                      setSelected((previous) =>
                        event.target.checked
                          ? [...previous, path]
                          : previous.filter((item) => item !== path),
                      )
                    }
                  />
                  {path}
                </label>
              ))}
            </div>
            {selected.length === 0 && (
              <p className="text-xs text-muted">请至少选择一个 Wiki 来源</p>
            )}
          </>
        )}
      </details>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-muted text-sm py-12">
            <BookOpen className="h-8 w-8" />
            <p>向你的 wiki 提问</p>
            <p>回答将仅使用勾选的 Wiki 来源</p>
          </div>
        )}
        {messages.map((message, index) => (
          <div
            key={index}
            className={`rounded-lg p-3 ${message.role === 'user' ? 'bg-primary text-text-inverse' : 'bg-bg-muted text-text'}`}
          >
            <div className="text-sm whitespace-pre-wrap">{message.content}</div>
            {message.error && <p role="alert">{message.error}</p>}
            {!!message.citations?.length && (
              <section aria-label="引用证据">
                <h3 className="text-xs my-2">引用证据</h3>
                {message.citations.map((citation) => (
                  <Citation key={citation.id} citation={citation} projectPath={projectPath} />
                ))}
              </section>
            )}
            {!!message.sources?.length && (
              <details className="text-xs mt-2">
                <summary>检索来源（不代表全部被引用）</summary>
                {message.sources.map((source) => (
                  <div key={source.id}>
                    {source.title} · {source.path}
                  </div>
                ))}
              </details>
            )}
          </div>
        ))}
        {loading && (
          <div className="text-sm whitespace-pre-wrap" role="status">
            {streamId ? stream.answer || '正在思考…' : '正在开始问答…'}
          </div>
        )}
      </div>
      <div className="border-t border-border p-3 flex gap-2">
        <input
          className="flex-1 min-w-0 border border-border rounded-md p-2 bg-bg-muted"
          placeholder="输入你的问题..."
          value={input}
          disabled={loading}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <button
          aria-label="发送问题"
          disabled={!canSend || !input.trim()}
          onClick={() => void send()}
          className="rounded-md px-3 bg-primary text-text-inverse disabled:opacity-50"
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
