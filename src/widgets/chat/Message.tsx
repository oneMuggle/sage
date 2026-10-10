import {
  BookOpen,
  Wrench,
  ChevronDown,
  FileText,
  Zap,
} from 'lucide-react';
import { memo, useMemo, useState } from 'react';

import type { Artifact } from '../../features/artifacts/artifactApi';
import { MediaAttachment } from '../../features/chat/MediaAttachment';
import { useRightPanelStore } from '../../features/right-panel/rightPanelStore';
import { THINKING_PLACEHOLDER } from '../../features/send-message/thinkingPlaceholder';
import { useI18n } from '../../shared/lib/i18n';
import { hasUnclosedFence, splitStableChunks } from '../../shared/lib/markdownChunks';
import type { Message as MessageType, ToolCall } from '../../shared/lib/store';

import { CompactBanner } from './CompactBanner';
import { MessageActionBar } from './MessageActionBar';
import {
  fileChangePaths,
  MarkdownChunk,
  renderTextWithLinks,
  ThinkingPanel,
  ThinkingShimmer,
  ToolCallResult,
  ToolCallTitle,
} from './MessageMarkdownParts';
import { TruncationNotice } from './TruncationNotice';
import { FileChangeCards } from './changes/FileChangeCard';
import { resolveToolRenderer } from './toolRenderers';

interface MessageProps {
  message: MessageType;
  onFeedback?: (messageId: string, feedback: 'up' | 'down') => void;
  knowledgeRefs?: { id: string; title: string }[];
  attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
  /** P1: 该消息是否正在流式输出 (用于 ThinkingPanel 自动展开) */
  isStreaming?: boolean;
  /** M4: 从此消息分叉新会话（非破坏性，无需确认） */
  onFork?: (messageId: string) => void;
  /** W1: 回滚到此处（对话 fork + 可选工作区快照恢复，Claude Code /rewind 对标） */
  onRewind?: (messageId: string) => void;
  /** U5': 编辑此条 user 消息并重发（分叉其前缀，原会话保留） */
  onEditResend?: (messageId: string) => void;
  /** R18-A: 重新生成此条 assistant 回答（fork 前缀 + 重发前驱 user 消息） */
  onRegenerate?: (messageId: string) => void;
  /** R17-B: 删除此条消息（两步确认，历史消息；流式中的消息不显示） */
  onDelete?: (messageId: string) => void;
  /** P0-1: 引用此条消息到输入框 */
  onQuote?: (message: MessageType) => void;
  /** P0-1: 将此条消息内容保存到长期记忆 */
  onSaveToMemory?: (message: MessageType) => void;
  /** 第二轮 B2: 截断回答的「继续生成」（MessageList 只传给会话最后一条消息） */
  onContinue?: () => void;
  /** 第二轮 C2: 回答版本切换后的回调（MessageList 只传给会话最后一条消息） */
  onAnswerVersionChange?: () => void;
  /** right-panel R1 批次 B: tool_call_id → 产物[] 映射 —— 命中的工具卡片
   * 下渲染内联产物 chip，点击直达右侧面板产物预览（对齐 Claude） */
  artifactsByToolCall?: Record<string, Artifact[]>;
}

// MEDIUM-5: React.memo 包装,自定义比较函数避免 ReactMarkdown 重解析
// - 仅当 message 引用变、isStreaming 变化、knowledgeRefs/attachments 引用变时才重渲染
// - 在每个 content_delta 触发 N 条历史消息重渲染的场景下,这是关键优化
function MessageComponent({
  message,
  onFeedback,
  knowledgeRefs,
  attachments,
  isStreaming,
  onFork,
  onRewind,
  onEditResend,
  onRegenerate,
  onDelete,
  onQuote,
  onSaveToMemory,
  onContinue,
  onAnswerVersionChange,
  artifactsByToolCall,
}: MessageProps) {
  const { t } = useI18n();
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const isSystem = message.role === 'system';
  const isError = message.content?.startsWith('[错误') ?? false;
  // 2026-09-13 P0: 首个 token 到达前 content 是哨兵占位值 — 渲染 shimmer
  // 骨架而非把 "🤔 思考中…" 当 markdown 静态文本展示。agent 中间态文案
  // (思考/调用工具) 会覆盖占位值，覆盖后自动回退 markdown 渲染。
  const isThinkingPlaceholder =
    isAssistant && isStreaming === true && message.content === THINKING_PLACEHOLDER;
  // 2026-09 step-by-step: 多步 run 中,中间步骤可能 content="" 但有
  // tool_calls / reasoning_content。气泡只在有内容时渲染;其他部件
  // (ThinkingPanel / tool_calls) 始终渲染,确保中间步骤不会"空泡"。
  const showBubble = isUser || (isAssistant && Boolean((message.content ?? '').trim()));

  // P1 流式分块: 已确定前缀切稳定块（memo 化跳过重解析），只有 live 尾块
  // 随 delta 全量 re-parse；非流式整体单块渲染，DOM 与旧实现一致。
  const displayContent = useMemo(
    () => message.content.replace(/<img\s+[^>]*src=["']data:[^"']*["'][^>]*\/?>/gi, ''),
    [message.content],
  );
  const chunks = useMemo(
    () =>
      isStreaming === true
        ? splitStableChunks(displayContent)
        : { stable: [], live: displayContent },
    [displayContent, isStreaming],
  );
  // 未闭合围栏: live 尾块里的半截代码降级纯文本，闭合后自动恢复高亮/mermaid
  const unclosedFence = useMemo(
    () => isStreaming === true && hasUnclosedFence(displayContent),
    [displayContent, isStreaming],
  );
  // 2026-09 修复: 历史消息的 tool_calls 从后端原样加载时是 JSON 字符串
  // (session_repo 不做 parse), 直接 .map 会崩。双态归一化。
  const toolCalls: ToolCall[] = useMemo(() => {
    const raw = message.tool_calls;
    if (Array.isArray(raw)) return raw;
    if (typeof raw === 'string' && raw) {
      try {
        const parsed = JSON.parse(raw) as unknown;
        return Array.isArray(parsed) ? (parsed as ToolCall[]) : [];
      } catch {
        return [];
      }
    }
    return [];
  }, [message.tool_calls]);
  // R38: 技能激活明细展开态
  const [skillsExpanded, setSkillsExpanded] = useState(false);
  const activatedSkills = message.activated_skills ?? [];
  // R81: 统一参考来源 —— 记忆召回 + 附件检索溯源 + 工具命中(web/wiki/MCP)
  // 收编为一个折叠区块（类文章引用列表），N=0 时整个 chip 不渲染。
  const [sourcesExpanded, setSourcesExpanded] = useState(false);
  const [toolGroupExpanded, setToolGroupExpanded] = useState(false);
  const canGroupToolCalls = useMemo(
    () =>
      !isStreaming &&
      toolCalls.length >= 3 &&
      !toolCalls.some(
        (tc) =>
          Boolean(tc.metadata?.blockReason) ||
          Boolean(tc.metadata?.imageData) ||
          Boolean(tc.metadata?.mediaRefs?.length) ||
          Boolean(tc.id && artifactsByToolCall?.[tc.id]?.length),
      ),
    [isStreaming, toolCalls, artifactsByToolCall],
  );
  const toolGroupSummary = useMemo(() => {
    if (!canGroupToolCalls) return '';
    const counts = new Map<string, number>();
    for (const tc of toolCalls) {
      counts.set(tc.name, (counts.get(tc.name) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .slice(0, 3)
      .map(([name, cnt]) => (cnt > 1 ? `${name}×${cnt}` : name))
      .join(' · ');
  }, [canGroupToolCalls, toolCalls]);
  const memoryRefs = message.memory_refs ?? [];
  const ragCitations = message.rag_citations ?? [];
  const toolSources = message.sources ?? [];
  // R86: @memory: 实体引用命中（kind='memory'）——与记忆召回同渲染进记忆分组
  const memorySources = toolSources.filter((s) => s.kind === 'memory');
  const wikiSources = toolSources.filter((s) => s.kind === 'wiki');
  const webSources = toolSources.filter((s) => s.kind === 'web');
  const mcpSources = toolSources.filter((s) => s.kind === 'tool');
  const sourcesTotal = memoryRefs.length + ragCitations.length + toolSources.length;
  // 各分组在统一编号里的起始偏移（列表带 [1][2]… 序号, 类文章引用）
  const ragOffset = memoryRefs.length + memorySources.length;
  const wikiOffset = ragOffset + ragCitations.length;
  const webOffset = wikiOffset + wikiSources.length;
  const toolOffset = webOffset + webSources.length;

  // R38: 系统消息（如压缩通知）居中渲染，无头像/气泡
  // 必须在所有 Hooks 之后 return，否则违反 React Hooks 规则
  if (isSystem && message.compact_info) {
    return (
      <div className="flex justify-center my-3">
        <CompactBanner info={message.compact_info} />
      </div>
    );
  }

  return (
    <div
      data-testid={isAssistant ? 'chat-message-assistant' : undefined}
      className={`flex gap-3 mb-[var(--density-msg-gap)] w-full animate-message-enter ${isUser ? 'flex-row-reverse' : ''}`}
    >
      {/* 头像 */}
      <div
        className={`w-7 h-7 rounded-radius-sm flex-shrink-0 flex items-center justify-center text-ui-sm font-semibold ${
          isAssistant ? 'bg-primary/10 text-primary' : 'bg-bg text-muted border border-border'
        }`}
      >
        {isAssistant ? 'S' : 'U'}
      </div>

      <div className={`flex-1 ${isUser ? 'flex flex-col items-end' : ''}`}>
        {/* R38: 压缩续接行 —— 横幅置于气泡上方，摘要正文/Thinking/
            copy/regenerate/delete 等正文与 affordance 全部保留。 */}
        {message.compact_info && <CompactBanner info={message.compact_info} />}

        {/* ThinkingPanel - LLM 思考过程展示（仅 assistant 消息且有 reasoning_content 时） */}
        {isAssistant && message.reasoning_content && (
          <ThinkingPanel reasoning={message.reasoning_content} isStreaming={isStreaming} />
        )}

        {/* Knowledge references */}
        {knowledgeRefs && knowledgeRefs.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-1">
            {knowledgeRefs.map((ref) => (
              <span
                key={ref.id}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs bg-primary/10 text-primary"
              >
                <BookOpen className="w-2.5 h-2.5" />
                {ref.title}
              </span>
            ))}
          </div>
        )}

        {/* File attachments */}
        {attachments && attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {attachments.map((file, idx) => (
              <span
                key={idx}
                className={`inline-flex items-center gap-1 px-2 py-1 rounded text-ui-sm border ${
                  isUser
                    ? 'bg-text-inverse/15 border-text-inverse/20 text-text-inverse'
                    : 'bg-bg-subtle border-border text-text-secondary'
                }`}
              >
                {file.type.startsWith('image/') && file.dataUrl ? (
                  <img src={file.dataUrl} alt="" className="w-4 h-4 rounded object-cover" />
                ) : null}
                <span className="truncate max-w-24">{file.name}</span>
              </span>
            ))}
          </div>
        )}

        {/* 工具调用展示（ReAct 模式）— 在消息内容之前，因为工具调用先于最终回答 */}
        {toolCalls.length > 0 && (
          <div className="mb-2 flex flex-col gap-1.5">
            {canGroupToolCalls && (
              <button
                type="button"
                data-testid="tool-calls-group-toggle"
                aria-expanded={toolGroupExpanded}
                onClick={() => setToolGroupExpanded((v) => !v)}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-radius-sm border border-border bg-bg-subtle hover:bg-bg-hover text-ui-xs text-text-secondary transition-colors text-left"
              >
                <Wrench className="w-3.5 h-3.5 text-primary shrink-0" />
                <span className="font-medium text-text">
                  已执行 {toolCalls.length} 步工具调用
                </span>
                <span className="text-text-tertiary truncate font-mono text-ui-2xs">
                  ({toolGroupSummary})
                </span>
                <span className="ml-auto inline-flex items-center gap-0.5 text-ui-2xs text-primary shrink-0">
                  {toolGroupExpanded ? '收起明细' : '展开明细'}
                  <ChevronDown
                    className={`w-3.5 h-3.5 transition-transform ${toolGroupExpanded ? 'rotate-180' : ''}`}
                  />
                </span>
              </button>
            )}
            {(!canGroupToolCalls || toolGroupExpanded) &&
              toolCalls.map((tc, idx) => {
              const hasImage = tc.metadata?.imageData;
              // right-panel R5: 写文件工具的内联 diff 卡片（展开懒加载,
              // 点击面板按钮直达右侧变更 Tab）
              const changePaths = message.session_id ? fileChangePaths(tc) : [];
              const isBlocked = Boolean(tc.metadata?.blockReason);
              const SpecializedRenderer = resolveToolRenderer(tc.name);

              // Artifact chips / image / media refs — 无论是否使用专用渲染器都渲染
              const extras = (
                <>
                  {tc.id && artifactsByToolCall?.[tc.id]?.length ? (
                    <div className="flex flex-wrap gap-1 px-2 pb-1.5">
                      {artifactsByToolCall[tc.id].map((art) => (
                        <button
                          key={art.id}
                          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-border bg-surface hover:bg-bg-hover text-ui-2xs text-primary transition-colors"
                          onClick={() => useRightPanelStore.getState().selectArtifact(art.id)}
                          title="在右侧面板中查看"
                          data-testid="message-artifact-chip"
                        >
                          <FileText className="w-3 h-3 shrink-0" />
                          <span className="truncate max-w-48">{art.name}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {hasImage && (
                    <div className="px-2 pb-2">
                      <img
                        src={tc.metadata!.imageData}
                        alt={`Diagram from ${tc.name}`}
                        className="max-w-full rounded border border-border"
                        style={{ maxHeight: '400px', backgroundColor: '#ffffff' }}
                      />
                    </div>
                  )}
                  {tc.metadata?.mediaRefs && tc.metadata.mediaRefs.length > 0 && (
                    <div className="px-2 pb-2">
                      {tc.metadata.mediaRefs.map((ref, refIdx) => (
                        <MediaAttachment
                          key={ref.id || refIdx}
                          url={ref.api_url ?? `/api/v1/media/${ref.id}`}
                          mimeType={ref.mime_type}
                          caption={`${ref.kind} — ${ref.source || tc.name}`}
                        />
                      ))}
                    </div>
                  )}
                </>
              );

              // 专用渲染器（ZCode-inspired） — 替代通用卡片头部+结果区
              if (SpecializedRenderer && !isBlocked) {
                return (
                  <div key={`${tc.name}-${idx}`} className="flex flex-col gap-1.5">
                    <SpecializedRenderer tc={tc} />
                    {changePaths.length > 0 && (
                      <FileChangeCards sessionId={message.session_id} paths={changePaths} />
                    )}
                    {extras}
                  </div>
                );
              }

              // 通用卡片（未注册专用渲染器 or 被拦截时走旧路径）
              return (
                <div
                  key={`${tc.name}-${idx}`}
                  className="flex flex-col gap-1.5 rounded border border-border bg-bg-subtle text-ui-sm"
                >
                  {/* Tool call header — U8: humanized title + 弱化的原始工具名(调试用) */}
                  <div className="flex flex-wrap items-center gap-1.5 px-2 py-1.5">
                    <Wrench className="w-3 h-3 text-primary shrink-0" />
                    <ToolCallTitle name={tc.name} args={tc.args} />
                    <span className="font-mono text-ui-xs text-muted">{tc.name}</span>
                  </div>
                  {/* right-panel R5/R6: 文件修改卡组（<3 个平铺,≥3 个折叠为汇总条） */}
                  {changePaths.length > 0 && (
                    <FileChangeCards sessionId={message.session_id} paths={changePaths} />
                  )}
                  {/* Tool result — 大文件内容可折叠 */}
                  {tc.result !== undefined && tc.result !== '' && !hasImage && (
                    <div className="px-2 pb-1.5">
                      <ToolCallResult result={tc.result} />
                    </div>
                  )}
                  {extras}
                </div>
              );
            })}
          </div>
        )}

        {/* 消息气泡 — 2026-09 step-by-step: 空内容时不渲染,避免空白气泡 */}
        {showBubble && (
        <div
          data-error={isError ? 'true' : undefined}
          data-quote-scope="message-body"
          className={`max-w-2xl px-[var(--density-msg-px)] py-[var(--density-msg-py)] rounded-radius-sm text-ui-caption leading-relaxed ${
            isUser
              ? 'bg-primary text-text-inverse'
              : isError
                ? 'bg-error/10 border border-error/40 text-error'
                : 'bg-surface border border-border'
          }`}
        >
          {/* Message content with Markdown */}
          {isAssistant ? (
            isThinkingPlaceholder ? (
              <ThinkingShimmer />
            ) : (
              <div className="max-w-none max-w-3xl mx-auto w-full">
                {/* P2: 阅读宽度约束 48rem 居中（对标主流 AI 应用），宽屏下
                    长文不再一行拉满；表格/代码块仍在容器内滚动 */}
                {chunks.stable.map((md, i) => (
                  <MarkdownChunk key={i} md={md} />
                ))}
                <MarkdownChunk md={chunks.live} plainFences={unclosedFence || undefined} />
                {/* 流式生成光标 — 跟随内容尾部闪烁（reduced-motion 全局关闭） */}
                {isStreaming && (
                  <span
                    className="stream-cursor"
                    aria-hidden="true"
                    data-testid="stream-cursor"
                  />
                )}
              </div>
            )
          ) : (
            <p className="whitespace-pre-wrap">{renderTextWithLinks(message.content)}</p>
          )}
        </div>
        )}

        {/* 底部信息 */}
        <div className="flex items-center gap-2 mt-1 text-ui-2xs text-muted">
          {/* R81: 统一参考来源 chip（记忆 + 附件检索 + 工具命中收编，
              原 memory-used / rag-citations 两个分散 chip 合并为此处） */}
          {sourcesTotal > 0 && (
            <button
              type="button"
              onClick={() => setSourcesExpanded((v) => !v)}
              className="inline-flex items-center gap-0.5 text-primary hover:underline"
              title={t('chat.sources_toggle')}
              data-testid="message-sources-toggle"
            >
              <BookOpen className="w-3 h-3" />
              {t('chat.sources_count').replace('{n}', String(sourcesTotal))}
              <ChevronDown
                className={`w-3 h-3 transition-transform ${sourcesExpanded ? 'rotate-180' : ''}`}
              />
            </button>
          )}
          {/* R38: 技能激活展示 */}
          {activatedSkills.length > 0 && (
            <button
              type="button"
              onClick={() => setSkillsExpanded((v) => !v)}
              className="inline-flex items-center gap-0.5 text-amber-600 dark:text-amber-400 hover:underline"
              title={t('chat.skills_toggle')}
              data-testid="skill-activated-toggle"
            >
              <Zap className="w-3 h-3" />
              {activatedSkills.length} {t('chat.skills_activated')}
              <ChevronDown
                className={`w-3 h-3 transition-transform ${skillsExpanded ? 'rotate-180' : ''}`}
              />
            </button>
          )}
          <span>
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>

        {/* R81: 统一参考来源区块 —— 记忆 / 附件检索 / 知识库 / 网页 / 工具，
            每条带统一序号 [n]（类文章引用），供用户核对来源可靠性。 */}
        {sourcesExpanded && sourcesTotal > 0 && (
          <div
            className="mt-1 p-2 rounded-radius-sm bg-bg-subtle border border-border text-ui-sm space-y-2"
            data-testid="message-sources-list"
          >
            {(memoryRefs.length > 0 || memorySources.length > 0) && (
              <div className="space-y-1">
                <div className="text-ui-xs font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_memory')}
                </div>
                {memoryRefs.map((ref, i) => (
                  <div key={`mem-${ref.id}-${i}`} className="flex items-start gap-1.5">
                    <span className="text-muted flex-shrink-0 font-mono">[{i + 1}]</span>
                    <span className="px-1 rounded bg-primary/10 text-primary flex-shrink-0">
                      {ref.memory_type}
                    </span>
                    <span className="text-text-secondary break-all">{ref.preview}</span>
                  </div>
                ))}
                {/* R86: @memory: 实体引用命中，序号与记忆召回连续 */}
                {memorySources.map((s, i) => (
                  <div key={`memsrc-${s.title}-${i}`} className="flex items-start gap-1.5">
                    <span className="text-muted flex-shrink-0 font-mono">
                      [{memoryRefs.length + i + 1}]
                    </span>
                    <span className="px-1 rounded bg-primary/10 text-primary flex-shrink-0">
                      @memory
                    </span>
                    <span className="text-text-secondary break-all">{s.snippet || s.title}</span>
                  </div>
                ))}
              </div>
            )}

            {ragCitations.length > 0 && (
              <div className="space-y-1">
                <div className="text-ui-xs font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_attachment')}
                </div>
                {ragCitations.map((c, i) => (
                  <div key={`rag-${c.media_id}-${i}`} className="space-y-0.5">
                    <div className="flex items-start gap-1.5">
                      <span className="text-muted flex-shrink-0 font-mono">
                        [{ragOffset + i + 1}]
                      </span>
                      <span className="text-text-secondary font-mono break-all">
                        {c.filename || c.media_id}
                      </span>
                    </div>
                    {(c.chunks ?? []).length > 0 && (
                      <div className="pl-5 text-muted font-mono">
                        {(c.chunks ?? [])
                          .map((ch) => `#${ch.index} (${ch.score.toFixed(2)})`)
                          .join(' ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {wikiSources.length > 0 && (
              <div className="space-y-1">
                <div className="text-ui-xs font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_wiki')}
                </div>
                {wikiSources.map((s, i) => (
                  <div key={`wiki-${s.path}-${i}`} className="space-y-0.5">
                    <div className="flex items-start gap-1.5">
                      <span className="text-muted flex-shrink-0 font-mono">
                        [{wikiOffset + i + 1}]
                      </span>
                      <span className="text-text-secondary font-mono break-all">
                        {s.title || s.path}
                      </span>
                      {s.score != null && (
                        <span className="text-muted flex-shrink-0">({s.score.toFixed(2)})</span>
                      )}
                    </div>
                    {s.snippet && <div className="pl-5 text-muted break-all">{s.snippet}</div>}
                  </div>
                ))}
              </div>
            )}

            {webSources.length > 0 && (
              <div className="space-y-1">
                <div className="text-ui-xs font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_web')}
                </div>
                {webSources.map((s, i) => (
                  <div key={`web-${s.url}-${i}`} className="space-y-0.5">
                    <div className="flex items-start gap-1.5">
                      <span className="text-muted flex-shrink-0 font-mono">
                        [{webOffset + i + 1}]
                      </span>
                      {s.url ? (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline break-all"
                        >
                          {s.title || s.url}
                        </a>
                      ) : (
                        <span className="text-text-secondary break-all">{s.title}</span>
                      )}
                    </div>
                    {s.snippet && <div className="pl-5 text-muted break-all">{s.snippet}</div>}
                  </div>
                ))}
              </div>
            )}

            {mcpSources.length > 0 && (
              <div className="space-y-1">
                <div className="text-ui-xs font-medium text-muted uppercase tracking-wide">
                  {t('chat.sources_group_tool')}
                </div>
                {mcpSources.map((s, i) => (
                  <div key={`tool-${s.server}-${s.tool}-${i}`} className="space-y-0.5">
                    <div className="flex items-start gap-1.5">
                      <span className="text-muted flex-shrink-0 font-mono">
                        [{toolOffset + i + 1}]
                      </span>
                      <span className="px-1 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400 flex-shrink-0">
                        {s.server}/{s.tool}
                      </span>
                    </div>
                    {s.preview && <div className="pl-5 text-muted break-all">{s.preview}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* R38: 技能激活明细（skill_activated 流事件携带，可展开） */}
        {skillsExpanded && activatedSkills.length > 0 && (
          <div
            className="mt-1 p-2 rounded-radius-sm bg-bg-subtle border border-border text-ui-sm space-y-1"
            data-testid="skill-activated-list"
          >
            {activatedSkills.map((skill) => (
              <div key={skill.name} className="flex flex-col gap-0.5">
                <div className="flex items-start gap-1.5">
                  <span className="px-1 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400 flex-shrink-0">
                    技能
                  </span>
                  <span className="text-text-secondary break-all">{skill.name}</span>
                </div>
                {/* MEDIUM-3: 展示命中的触发词（extract_triggers 已小写化） */}
                {skill.triggers_matched && skill.triggers_matched.length > 0 && (
                  <div className="ml-5 flex flex-wrap gap-1">
                    {skill.triggers_matched.map((trigger, idx) => (
                      <span
                        key={idx}
                        className="px-1 py-0.5 rounded bg-bg-hover text-text-tertiary text-ui-xs"
                      >
                        {trigger}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 第二轮 B2: 触达输出上限被截断时提示；最后一条消息附带「继续生成」 */}
        {isAssistant && !isStreaming && (
          <TruncationNotice finishReason={message.finish_reason} onContinue={onContinue} />
        )}

        {/* Action buttons */}
        <MessageActionBar
          message={message}
          isStreaming={isStreaming}
          onFeedback={onFeedback}
          onFork={onFork}
          onRewind={onRewind}
          onEditResend={onEditResend}
          onRegenerate={onRegenerate}
          onDelete={onDelete}
          onQuote={onQuote}
          onSaveToMemory={onSaveToMemory}
          onAnswerVersionChange={onAnswerVersionChange}
        />
      </div>
    </div>
  );
}

export const Message = memo(MessageComponent, (prev, next) => {
  // 自定义比较:仅当 message 对象引用变化 / isStreaming 变化 / 关联数据变化时重渲染
  // ReactMarkdown 和 Prism SyntaxHighlighter 很重,跳过能显著降低 token 级重渲染成本
  return (
    prev.message === next.message &&
    prev.isStreaming === next.isStreaming &&
    prev.onContinue === next.onContinue &&
    prev.onAnswerVersionChange === next.onAnswerVersionChange &&
    prev.onFeedback === next.onFeedback &&
    prev.knowledgeRefs === next.knowledgeRefs &&
    prev.attachments === next.attachments &&
    prev.onFork === next.onFork &&
    prev.onEditResend === next.onEditResend &&
    prev.onRegenerate === next.onRegenerate &&
    prev.onDelete === next.onDelete &&
    prev.onQuote === next.onQuote &&
    prev.onSaveToMemory === next.onSaveToMemory &&
    prev.artifactsByToolCall === next.artifactsByToolCall
  );
});
