/**
 * `FactReconBlock` — 「事实侦察」可折叠区块（2026-11-27）。
 *
 * 背景：此前事实侦察只以三行滚动文本混在规划时间线里，用户无法核对
 * 侦察到的事实是否正确、完整。本块把侦察结果提升为独立区块：
 *
 * - 折叠头：`事实侦察 · N 条事实 · 12.3s`（参考 Claude Code「Thought for 8s」
 *   与 Perplexity 的 Steps 手风琴）；
 * - 展开体：逐条列出事实正文（**完整换行显示，不截断**）+ 来源 chip，
 *   用户可逐条核对；
 * - 二级折叠：`侦察过程（N）` —— 思考 / 工具调用 / 结果的过程轨迹
 *   （参考 ChatGPT Deep Research 的 activity steps）。
 *
 * 数据源优先级：实时 store（scout 阶段 facts + lines）> 落库回读的
 * `client_meta.scout_facts`（刷新会话后仍可见）。
 */
import { ChevronDown, ListChecks } from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  selectSessionSlots,
  useChatStreamStore,
} from '../../features/send-message/chatStreamStore';
import type { PlanStageState } from '../../features/send-message/planProgress';
import type { ScoutFact, ScoutFactsMeta } from '../../shared/api/types/chatAndEventTypes';

export interface FactReconBlockProps {
  sessionId: string | null | undefined;
  /** 当前气泡的消息 id —— 只有正在流式输出的那条气泡才吃实时数据。 */
  messageId?: string;
  /** 落库回读的事实清单（`message.client_meta.scout_facts`）。 */
  persistedFacts?: ScoutFactsMeta | null;
}

function isScoutActive(stage: PlanStageState | undefined): boolean {
  if (!stage) return false;
  return stage.status === 'started' || stage.status === 'progress';
}

export function FactReconBlock({ sessionId, messageId, persistedFacts }: FactReconBlockProps) {
  const stages = useChatStreamStore((s) => selectSessionSlots(s, sessionId).planProgress);
  const streamingMessageId = useChatStreamStore(
    (s) => selectSessionSlots(s, sessionId).streaming?.messageId ?? null,
  );

  // 用户手动切换优先于自动展开策略（manual !== null ? manual : auto）。
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);
  const [manualProcessExpanded, setManualProcessExpanded] = useState<boolean | null>(null);

  // 实时数据只挂在当前流式消息上 —— 否则每条历史气泡都会重复渲染。
  const isStreamingMessage = Boolean(messageId) && streamingMessageId === messageId;
  const liveStage = isStreamingMessage
    ? stages?.find((stage) => stage.stage === 'scout')
    : undefined;

  const liveFacts = liveStage?.facts ?? [];
  const persistedList = persistedFacts?.facts ?? [];
  // 实时优先；实时为空时回落落库清单。
  const facts: ScoutFact[] = liveFacts.length > 0 ? liveFacts : persistedList;
  const factCount = liveFacts.length > 0 ? liveFacts.length : persistedList.length;
  const truncated = liveStage?.factsTruncated ?? persistedFacts?.truncated ?? false;
  const processLines = liveStage?.lines ?? [];
  const elapsedMs = liveStage?.elapsedMs;
  const scoutActive = isScoutActive(liveStage);

  // 侦察一旦开始过就保持自动展开：facts 只在 DONE 事件才带出，若在 DONE
  // 瞬间自动收起，用户会看到"刚填满就收起"—— 与核对事实的目标相悖。
  // 落库态（刷新后回看）不触发自动展开，默认折叠。
  const [autoOpened, setAutoOpened] = useState(() => scoutActive);
  useEffect(() => {
    if (scoutActive) setAutoOpened(true);
  }, [scoutActive]);

  const autoExpand = scoutActive || autoOpened;
  const expanded = manualExpanded ?? autoExpand;
  const processExpanded = manualProcessExpanded ?? autoExpand;

  if (!liveStage && facts.length === 0) return null;

  return (
    <div
      data-testid="fact-recon-block"
      className="mb-2 px-3 py-2 rounded-radius-sm border border-border bg-bg-subtle text-ui-xs leading-relaxed"
    >
      <button
        type="button"
        data-testid="fact-recon-toggle"
        aria-expanded={expanded}
        aria-label={expanded ? '折叠事实侦察' : '展开事实侦察'}
        onClick={() => setManualExpanded(!expanded)}
        className="w-full flex items-center justify-between gap-2 text-left hover:text-text transition-colors"
      >
        <span className="flex items-center gap-1.5 min-w-0">
          <ListChecks className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
          <span className="font-medium">事实侦察</span>
          {factCount > 0 && (
            <span data-testid="fact-recon-count" className="text-text-muted">
              · {factCount} 条事实
            </span>
          )}
          {scoutActive && (
            <span data-testid="fact-recon-running" className="text-text-muted">
              · 侦察中
            </span>
          )}
          {typeof elapsedMs === 'number' && elapsedMs > 0 && (
            <span className="text-text-muted">· {(elapsedMs / 1000).toFixed(1)}s</span>
          )}
        </span>
        <ChevronDown
          className={`w-3.5 h-3.5 shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>

      {expanded && (
        <div className="mt-1.5 space-y-2">
          {facts.length > 0 && (
            <ol className="space-y-1.5" data-testid="fact-recon-list">
              {facts.map((fact, index) => (
                <li
                  key={`${index}-${fact.text.slice(0, 24)}`}
                  data-testid={`fact-recon-item-${index}`}
                  className="flex gap-1.5"
                >
                  <span className="text-text-muted shrink-0 tabular-nums">{index + 1}.</span>
                  <div className="min-w-0 flex-1">
                    {/* 正文完整换行显示 —— 用户要核对事实是否被截断/遗漏 */}
                    <div className="whitespace-pre-wrap break-words text-ui-sm text-text">
                      {fact.text}
                    </div>
                    {fact.source && (
                      <span
                        data-testid="fact-recon-source"
                        className="mt-0.5 inline-block max-w-full px-1 py-0.5 rounded bg-bg-hover text-ui-2xs text-text-muted break-words"
                      >
                        来源：{fact.source}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}

          {truncated && (
            <div data-testid="fact-recon-truncated" className="text-text-muted">
              事实条数超过展示上限，仅显示前 {factCount} 条。
            </div>
          )}

          {processLines.length > 0 && (
            <div>
              <button
                type="button"
                data-testid="fact-recon-process-toggle"
                aria-expanded={processExpanded}
                onClick={() => setManualProcessExpanded(!processExpanded)}
                className="inline-flex items-center gap-1 px-1 py-0.5 rounded text-text-muted hover:text-text hover:bg-bg-hover transition-colors"
              >
                <span>侦察过程（{processLines.length}）</span>
                <ChevronDown
                  className={`w-3 h-3 transition-transform ${processExpanded ? 'rotate-180' : ''}`}
                  aria-hidden="true"
                />
              </button>
              {processExpanded && (
                <ul
                  data-testid="fact-recon-process"
                  className="ml-3 mt-0.5 space-y-0.5 text-text-muted"
                >
                  {processLines.map((line, index) => (
                    <li
                      key={`${line.kind}-${index}`}
                      data-testid="fact-recon-process-line"
                      className="truncate"
                    >
                      {line.text}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
