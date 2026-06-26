// Wiki Research Panel - Deep Research 界面
import { useState } from 'react';

import {
  startWikiResearch,
  type ResearchResponse,
  type WebResultData,
} from '../../shared/api-client/wiki';

interface WikiResearchPanelProps {
  projectPath: string;
  llmBaseUrl: string;
  llmApiKey: string;
  llmModel: string;
  searchProvider?: string;
  searchApiKey?: string;
  searchBaseUrl?: string;
}

type ResearchStatus = 'idle' | 'searching' | 'synthesizing' | 'done' | 'error';

interface ResearchState {
  status: ResearchStatus;
  topic: string;
  result: ResearchResponse | null;
  error: string | null;
}

export function WikiResearchPanel({
  projectPath,
  llmBaseUrl,
  llmApiKey,
  llmModel,
  searchProvider = 'tavily',
  searchApiKey = '',
  searchBaseUrl = '',
}: WikiResearchPanelProps) {
  const [topic, setTopic] = useState('');
  const [autoIngest, setAutoIngest] = useState(true);
  const [state, setState] = useState<ResearchState>({
    status: 'idle',
    topic: '',
    result: null,
    error: null,
  });

  const startResearch = async () => {
    if (!topic.trim()) return;

    setState({ status: 'searching', topic, result: null, error: null });

    try {
      // 先设置为 searching 显示进度
      setTimeout(() => {
        setState((s) => (s.status === 'searching' ? { ...s, status: 'synthesizing' } : s));
      }, 2000);

      const result = await startWikiResearch({
        topic: topic.trim(),
        project_path: projectPath,
        search_provider: searchProvider,
        search_api_key: searchApiKey,
        search_base_url: searchBaseUrl,
        llm_base_url: llmBaseUrl,
        llm_api_key: llmApiKey,
        llm_model: llmModel,
        auto_ingest: autoIngest,
      });

      setState({
        status: result.status === 'done' ? 'done' : 'error',
        topic,
        result,
        error: result.error || null,
      });
    } catch (e) {
      setState({
        status: 'error',
        topic,
        result: null,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const reset = () => {
    setTopic('');
    setState({ status: 'idle', topic: '', result: null, error: null });
  };

  if (state.status === 'idle' || state.status === 'error') {
    return (
      <div className="h-full overflow-y-auto p-6 max-w-3xl mx-auto">
        <h2 className="text-xl font-semibold mb-2">🔬 Deep Research</h2>
        <p className="text-sm text-muted mb-6">
          输入研究主题，系统将自动搜索网络、收集来源、LLM 综合，并可选地保存到 Wiki。
        </p>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">研究主题</label>
            <textarea
              className="w-full px-3 py-2 border border-border rounded-md bg-surface text-sm"
              rows={3}
              placeholder="例如：2026 年 AI 代理的发展趋势"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="autoIngest"
              checked={autoIngest}
              onChange={(e) => setAutoIngest(e.target.checked)}
            />
            <label htmlFor="autoIngest" className="text-sm">
              自动 Ingest 到 Wiki
            </label>
          </div>

          {state.error && (
            <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm">
              ❌ {state.error}
            </div>
          )}

          <button
            className="w-full py-2 px-4 bg-accent text-white rounded-md hover:bg-accent/90 disabled:opacity-50"
            onClick={startResearch}
            disabled={!topic.trim()}
          >
            开始研究
          </button>
        </div>
      </div>
    );
  }

  if (state.status === 'searching' || state.status === 'synthesizing') {
    return (
      <div className="h-full flex flex-col items-center justify-center p-6">
        <div className="text-4xl mb-4 animate-pulse">🔬</div>
        <h3 className="text-lg font-semibold mb-2">{state.topic}</h3>
        <div className="text-sm text-muted">
          {state.status === 'searching' ? '正在搜索网络...' : '正在综合报告...'}
        </div>
        <div className="mt-4 w-64 h-2 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-accent transition-all duration-1000"
            style={{ width: state.status === 'searching' ? '30%' : '70%' }}
          />
        </div>
      </div>
    );
  }

  // done
  return (
    <div className="h-full overflow-y-auto p-6 max-w-3xl mx-auto">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-xl font-semibold">{state.topic}</h2>
          <p className="text-sm text-muted mt-1">
            {state.result?.web_results_count} 个来源 · {state.result?.queries.length} 个查询
          </p>
        </div>
        <button
          className="px-3 py-1 text-sm border border-border rounded-md hover:bg-muted"
          onClick={reset}
        >
          新研究
        </button>
      </div>

      {state.result?.saved_path && (
        <div className="p-3 rounded-md bg-green-500/10 text-green-700 text-sm mb-4">
          ✅ 已保存到 Wiki: <code className="text-xs">{state.result.saved_path}</code>
        </div>
      )}

      <div className="prose prose-sm max-w-none">
        <pre className="whitespace-pre-wrap text-sm bg-surface p-4 rounded-md border border-border">
          {state.result?.synthesis}
        </pre>
      </div>

      {state.result?.web_results && state.result.web_results.length > 0 && (
        <details className="mt-6">
          <summary className="cursor-pointer text-sm font-medium text-muted">
            查看 {state.result.web_results.length} 个来源
          </summary>
          <div className="mt-3 space-y-2">
            {state.result.web_results.map((r: WebResultData, i: number) => (
              <SourceCard key={i} index={i + 1} source={r} />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function SourceCard({ index, source }: { index: number; source: WebResultData }) {
  return (
    <div className="p-3 rounded-md border border-border bg-surface">
      <div className="flex items-start gap-2">
        <span className="text-xs font-mono text-muted mt-0.5">[{index}]</span>
        <div className="flex-1 min-w-0">
          <a
            className="text-sm font-medium hover:underline"
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {source.title}
          </a>
          <p className="text-xs text-muted mt-1 line-clamp-2">{source.snippet}</p>
          <p className="text-xs text-muted mt-1 truncate">{source.url}</p>
        </div>
      </div>
    </div>
  );
}
