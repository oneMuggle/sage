/**
 * AI 对话知识提取面板 (M2, 2026-10-12)
 *
 * 嵌入项目画像 Profile Tab 顶部，用户输入会话 ID 后一键提取知识建议，
 * 勾选确认后写入 ProjectProfileStore。
 */

import { Sparkles, Loader2, CheckCircle2, Lightbulb } from 'lucide-react';
import { useState, useCallback } from 'react';

import { projectApi, type KnowledgeEntryProposal } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';

export interface KnowledgeExtractionPanelProps {
  projectId: string;
  /** 提取并确认后回调（外部重新拉取画像列表） */
  onConfirmed?: () => void;
}

type Phase = 'idle' | 'loading' | 'review' | 'confirming';

const CATEGORY_LABELS: Record<string, string> = {
  convention: '约定',
  architecture: '架构',
  decision: '决策',
  goal: '目标',
  note: '备注',
};

export function KnowledgeExtractionPanel({
  projectId,
  onConfirmed,
}: KnowledgeExtractionPanelProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [entries, setEntries] = useState<KnowledgeEntryProposal[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [reasoning, setReasoning] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState('');

  const handleExtract = useCallback(async () => {
    if (!sessionId.trim()) {
      setError('请输入会话 ID');
      return;
    }
    setError(null);
    setPhase('loading');
    try {
      const result = await projectApi.extractKnowledge(projectId, {
        sessionId: sessionId.trim(),
      });
      setEntries(result.entries);
      setReasoning(result.reasoning);
      // 默认全选
      setSelected(new Set(result.entries.map((_, i) => i)));
      setPhase('review');
    } catch (err) {
      setError(err instanceof Error ? err.message : '知识提取失败');
      setPhase('idle');
    }
  }, [projectId, sessionId]);

  const handleConfirm = useCallback(async () => {
    if (selected.size === 0) return;
    setError(null);
    setPhase('confirming');
    try {
      const selectedEntries = [...selected].sort((a, b) => a - b).map((i) => entries[i]);
      await projectApi.confirmKnowledge(projectId, {
        entries: selectedEntries,
      });
      onConfirmed?.();
      resetPanel();
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败');
      setPhase('review');
    }
  }, [projectId, entries, selected, onConfirmed]);

  const resetPanel = () => {
    setPhase('idle');
    setEntries([]);
    setSelected(new Set());
    setReasoning('');
    setError(null);
  };

  const toggleEntry = (idx: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  return (
    <div className="space-y-3" data-testid="knowledge-extraction-panel">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {/* 输入阶段 */}
      {(phase === 'idle' || phase === 'loading') && (
        <div className="flex flex-wrap gap-2 items-center">
          <Lightbulb className="h-3.5 w-3.5 text-primary shrink-0" />
          <input
            type="text"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            placeholder="输入要分析的会话 ID..."
            disabled={phase === 'loading'}
            data-testid="knowledge-session-id-input"
            className="flex-1 min-w-[200px] rounded-md border border-input bg-background px-2.5 py-1.5 text-xs"
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void handleExtract()}
            disabled={!sessionId.trim() || phase === 'loading'}
            data-testid="knowledge-extract-btn"
          >
            {phase === 'loading' ? (
              <>
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                分析中...
              </>
            ) : (
              <>
                <Sparkles className="mr-1 h-3 w-3 text-primary" />
                AI 提取知识
              </>
            )}
          </Button>
        </div>
      )}

      {/* 审核阶段 */}
      {(phase === 'review' || phase === 'confirming') && (
        <div className="space-y-2">
          {reasoning && (
            <div className="rounded-lg border bg-muted/50 p-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">提取思路：</span> {reasoning}
            </div>
          )}
          {entries.length === 0 ? (
            <div className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
              本次分析未发现值得提取的知识
            </div>
          ) : (
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-muted-foreground">
                发现 {entries.length} 条建议，勾选要添加的：
              </div>
              {entries.map((entry, idx) => (
                <label
                  key={idx}
                  className="flex items-start gap-2 rounded-md border border-border bg-card px-3 py-2 text-xs cursor-pointer hover:bg-muted/30"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(idx)}
                    onChange={() => toggleEntry(idx)}
                    className="mt-0.5 shrink-0"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <Badge variant="outline" className="text-ui-2xs shrink-0">
                        {CATEGORY_LABELS[entry.category] ?? entry.category}
                      </Badge>
                      <span className="text-ui-2xs text-muted-foreground">
                        重要性 {entry.importance}/10
                      </span>
                    </div>
                    <p className="mt-0.5 text-foreground">{entry.content}</p>
                    {entry.reasoning && (
                      <p className="mt-0.5 text-muted-foreground text-ui-2xs">{entry.reasoning}</p>
                    )}
                  </div>
                </label>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={resetPanel}>
              取消
            </Button>
            <Button
              size="sm"
              onClick={() => void handleConfirm()}
              disabled={selected.size === 0 || phase === 'confirming'}
              data-testid="knowledge-confirm-btn"
            >
              {phase === 'confirming' ? (
                <>
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  写入中...
                </>
              ) : (
                <>
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  确认添加 ({selected.size})
                </>
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
