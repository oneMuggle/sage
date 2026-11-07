// src/features/feedback/FeedbackHub.tsx
//
// 用户反馈会话页：左侧会话列表，右侧消息流 + 输入框。
// 管理员回复由 Electron 主进程的 FeedbackSyncer 拉取后落进本地 SQLite，
// 这里只读本地数据（经 feedbackStore），不直接访问管理员地址。
//
<<<<<<< HEAD
// 设计见 docs/technical/111-feedback-relay-deployment.md §11.2。
=======
// 设计见 docs/technical/109-feedback-relay-deployment.md §11.2。
>>>>>>> origin/main

import { clsx } from 'clsx';
import { useEffect, useRef, useState, type ChangeEvent } from 'react';

import {
  FEEDBACK_TAGS,
  searchMessages,
  uploadAttachment,
  type FeedbackSearchHitDto,
  type FeedbackTag,
} from '../../shared/api/feedbackApi';
import { useI18n } from '../../shared/lib/i18n';

import { collectDiagnosticsSuffix } from './diagnosticsSuffix';
import { useFeedbackStore } from './feedbackStore';
import { buildSearchSnippet } from './searchSnippet';

const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;

const TAG_FILTERS: readonly (FeedbackTag | 'all')[] = ['all', ...FEEDBACK_TAGS];

function formatTimestamp(ms: number): string {
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

/** 分块转 base64，避免 String.fromCharCode(...bytes) 在大文件上爆栈。 */
function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

type FeedbackStatusKey =
  | 'feedback.hub.status.open'
  | 'feedback.hub.status.resolved'
  | 'feedback.hub.status.closed';

/**
 * 组装会话首条消息正文：开关打开时在用户正文后追加最近日志。
 * 读配置或取日志失败都不影响建会话。
 */
async function buildInitialBody(body: string, header: string): Promise<string> {
  let includeDiagnostics = false;
  try {
    const config = await window.electronAPI?.feedback?.getConfig();
    includeDiagnostics = Boolean(config?.includeDiagnostics);
  } catch {
    return body;
  }
  if (!includeDiagnostics) return body;
  const suffix = await collectDiagnosticsSuffix(header);
  if (!suffix) return body;
  return body ? `${body}\n\n${suffix}` : suffix;
}

function statusLabelKey(status: string): FeedbackStatusKey {
  if (status === 'resolved') return 'feedback.hub.status.resolved';
  if (status === 'closed') return 'feedback.hub.status.closed';
  return 'feedback.hub.status.open';
}

type FeedbackTagKey =
  | 'feedback.hub.tag.bug'
  | 'feedback.hub.tag.feature'
  | 'feedback.hub.tag.other';

function tagLabelKey(tag: string): FeedbackTagKey {
  if (tag === 'bug') return 'feedback.hub.tag.bug';
  if (tag === 'feature') return 'feedback.hub.tag.feature';
  return 'feedback.hub.tag.other';
}

export function FeedbackHub() {
  const { t } = useI18n();
  const conversations = useFeedbackStore((s) => s.conversations);
  const detailById = useFeedbackStore((s) => s.detailById);
  const currentId = useFeedbackStore((s) => s.currentId);
  const loading = useFeedbackStore((s) => s.loading);
  const errors = useFeedbackStore((s) => s.errors);
  const syncStats = useFeedbackStore((s) => s.syncStats);
  const logTail = useFeedbackStore((s) => s.logTail);

  const refreshList = useFeedbackStore((s) => s.refreshList);
  const openConversation = useFeedbackStore((s) => s.openConversation);
  const createAndOpen = useFeedbackStore((s) => s.createAndOpen);
  const sendMessage = useFeedbackStore((s) => s.sendMessage);
  const setStatus = useFeedbackStore((s) => s.setStatus);
  const triggerSync = useFeedbackStore((s) => s.triggerSync);
  const refreshLogTail = useFeedbackStore((s) => s.refreshLogTail);

  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [tag, setTag] = useState<FeedbackTag>('other');
  const [tagFilter, setTagFilter] = useState<FeedbackTag | 'all'>('all');
  const [draft, setDraft] = useState('');
  const [pendingMediaIds, setPendingMediaIds] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchHits, setSearchHits] = useState<FeedbackSearchHitDto[]>([]);
  const [searching, setSearching] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  // 输入停顿 250ms 再查，避免每个按键打一次 backend。
  useEffect(() => {
    const query = searchQuery.trim();
    if (!query) {
      setSearchHits([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    let cancelled = false;
    const timer = setTimeout(() => {
      void searchMessages(query)
        .then((hits) => {
          if (!cancelled) setSearchHits(hits);
        })
        .catch(() => {
          if (!cancelled) setSearchHits([]);
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [searchQuery]);

  const detail = currentId ? detailById[currentId] : undefined;
  const messages = detail?.messages ?? [];
  const detailLoading = currentId ? loading.detail[currentId] : false;
  const detailError = currentId ? errors.detail[currentId] : null;
  const searchActive = searchQuery.trim().length > 0;
  const filteredConversations =
    tagFilter === 'all'
      ? conversations
      : conversations.filter((c) => (c.tag || 'other') === tagFilter);

  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [currentId, messages.length]);

  const handleCreate = async (): Promise<void> => {
    if (!title.trim() || loading.create) return;
    setLocalError(null);
    const id = await createAndOpen({
      title: title.trim(),
      tag,
      body: await buildInitialBody(body.trim(), t('feedback.hub.diagnostics_suffix_header')),
    });
    if (id) {
      setTitle('');
      setBody('');
      setTag('other');
      setCreating(false);
    } else {
      setLocalError(useFeedbackStore.getState().errors.submit ?? t('feedback.hub.create_failed'));
    }
  };

  const handleSend = async (): Promise<void> => {
    const text = draft.trim();
    if (!currentId || loading.send) return;
    if (!text && pendingMediaIds.length === 0) return;
    setLocalError(null);
    const ok = await sendMessage({
      body: text,
      mediaIds: pendingMediaIds.length > 0 ? pendingMediaIds : undefined,
    });
    if (ok) {
      setDraft('');
      setPendingMediaIds([]);
    } else {
      setLocalError(useFeedbackStore.getState().errors.submit ?? t('feedback.hub.send_failed'));
    }
  };

  const handleAttach = async (event: ChangeEvent<HTMLInputElement>): Promise<void> => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (!currentId || files.length === 0) return;
    setLocalError(null);
    setUploading(true);
    try {
      const uploaded: string[] = [];
      for (const file of files) {
        if (file.size > MAX_ATTACHMENT_BYTES) {
          setLocalError(t('feedback.hub.upload_too_big'));
          continue;
        }
        const buffer = await file.arrayBuffer();
        const result = await uploadAttachment({
          conversationId: currentId,
          filename: file.name,
          mimeType: file.type || 'application/octet-stream',
          dataBase64: toBase64(buffer),
        });
        uploaded.push(result.id);
      }
      if (uploaded.length > 0) {
        setPendingMediaIds((prev) => [...prev, ...uploaded]);
      }
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : t('feedback.hub.upload_failed'));
    } finally {
      setUploading(false);
    }
  };

  const handleToggleStatus = async (): Promise<void> => {
    if (!detail) return;
    const next = detail.conversation.status === 'resolved' ? 'open' : 'resolved';
    setLocalError(null);
    const ok = await setStatus(detail.conversation.id, next);
    if (!ok) {
      setLocalError(useFeedbackStore.getState().errors.submit ?? t('feedback.hub.send_failed'));
    }
  };

  const handleToggleLog = (): void => {
    const next = !showLog;
    setShowLog(next);
    if (next && !logTail) void refreshLogTail();
  };

  const syncSummary = syncStats
    ? t('feedback.hub.sync_done')
        .replace('{submitted}', String(syncStats.submitted))
        .replace('{received}', String(syncStats.received))
        .replace('{errors}', String(syncStats.errors))
    : null;

  const attachmentCount = (count: number): string =>
    t('feedback.hub.attachments_count').replace('{count}', String(count));

  return (
    <div className="flex h-full min-h-0 bg-bg" data-testid="feedback-hub">
      {/* ───────── 左栏：会话列表 ───────── */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-surface">
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <h1 className="truncate text-ui-sm font-semibold text-ink">{t('feedback.hub.title')}</h1>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              data-testid="feedback-sync"
              disabled={loading.sync}
              onClick={() => void triggerSync()}
              className="rounded border border-border px-2 py-1 text-ui-xs text-text hover:bg-bg-hover disabled:opacity-50"
            >
              {loading.sync ? t('settings.feedback.syncing') : t('feedback.hub.sync')}
            </button>
            <button
              type="button"
              data-testid="feedback-new"
              onClick={() => {
                setCreating(true);
                setLocalError(null);
              }}
              className="rounded bg-primary px-2 py-1 text-ui-xs text-white hover:opacity-90"
            >
              {t('feedback.hub.new')}
            </button>
          </div>
        </div>

        <div className="border-b border-border px-3 py-2">
          <input
            type="search"
            data-testid="feedback-search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('feedback.hub.search.placeholder')}
            className="w-full rounded-md border border-border bg-bg px-2 py-1 text-ui-xs text-text placeholder:text-muted"
          />
        </div>

        {searchActive ? (
          <div className="min-h-0 flex-1 overflow-y-auto" data-testid="feedback-search-results">
            {searching ? (
              <p className="px-3 py-3 text-ui-xs text-muted">
                {t('feedback.hub.search.searching')}
              </p>
            ) : searchHits.length === 0 ? (
              <p className="px-3 py-3 text-ui-xs text-muted">{t('feedback.hub.search.empty')}</p>
            ) : (
              searchHits.map((hit) => (
                <button
                  key={hit.message_id}
                  type="button"
                  data-testid={`feedback-search-hit-${hit.message_id}`}
                  onClick={() => {
                    setCreating(false);
                    setSearchQuery('');
                    void openConversation(hit.conversation_id);
                  }}
                  className="block w-full border-b border-border/60 px-3 py-2 text-left hover:bg-bg-hover"
                >
                  <span className="block truncate text-ui-sm text-text">
                    {hit.conversation_title}
                  </span>
                  <span className="mt-0.5 block break-words text-ui-2xs text-muted">
                    {buildSearchSnippet(hit.body, searchQuery)}
                  </span>
                </button>
              ))
            )}
          </div>
        ) : (
          <>
            <div
              className="flex flex-wrap gap-1 border-b border-border px-3 py-2"
              data-testid="feedback-tag-filter"
            >
              {TAG_FILTERS.map((value) => (
                <button
                  key={value}
                  type="button"
                  data-testid={`feedback-tag-filter-${value}`}
                  aria-pressed={tagFilter === value}
                  onClick={() => setTagFilter(value)}
                  className={clsx(
                    'rounded-full border px-2 py-0.5 text-ui-2xs',
                    tagFilter === value
                      ? 'border-primary bg-primary text-white'
                      : 'border-border text-muted hover:bg-bg-hover',
                  )}
                >
                  {value === 'all' ? t('feedback.hub.filter.all') : t(tagLabelKey(value))}
                </button>
              ))}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {filteredConversations.length === 0 ? (
                <p className="px-3 py-3 text-ui-xs text-muted">
                  {loading.list ? t('feedback.hub.loading') : t('feedback.hub.list.empty')}
                </p>
              ) : (
                filteredConversations.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    data-testid={`feedback-conversation-${c.id}`}
                    onClick={() => {
                      setCreating(false);
                      void openConversation(c.id);
                    }}
                    className={clsx(
                      'block w-full border-b border-border/60 px-3 py-2 text-left hover:bg-bg-hover',
                      c.id === currentId && 'bg-bg-hover',
                    )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-ui-sm text-text">{c.title}</span>
                      <span className="shrink-0 text-ui-2xs text-muted">
                        {t(statusLabelKey(c.status))}
                      </span>
                    </span>
                    <span className="mt-0.5 flex items-center gap-2 text-ui-2xs text-muted">
                      <span
                        data-testid={`feedback-conversation-tag-${c.id}`}
                        className="rounded-full border border-border px-1.5 py-px"
                      >
                        {t(tagLabelKey(c.tag))}
                      </span>
                      <span>{formatTimestamp(c.last_activity_at)}</span>
                    </span>
                  </button>
                ))
              )}
            </div>
          </>
        )}

        {(errors.list || syncSummary) && (
          <p
            role={errors.list ? 'alert' : 'status'}
            className={clsx(
              'border-t border-border px-3 py-2 text-ui-2xs',
              errors.list ? 'text-danger' : 'text-muted',
            )}
          >
            {errors.list ?? syncSummary}
          </p>
        )}
      </aside>

      {/* ───────── 右栏：详情 / 新建 ───────── */}
      <section className="flex min-w-0 flex-1 flex-col">
        {creating ? (
          <div className="flex-1 space-y-4 overflow-y-auto p-4" data-testid="feedback-new-form">
            <h2 className="text-ui-lg font-semibold text-ink">{t('feedback.hub.new')}</h2>
            <div className="space-y-1">
              <span className="text-ui-sm text-muted">{t('feedback.hub.tag.label')}</span>
              <div className="flex gap-2">
                {FEEDBACK_TAGS.map((value) => (
                  <button
                    key={value}
                    type="button"
                    data-testid={`feedback-new-tag-${value}`}
                    aria-pressed={tag === value}
                    onClick={() => setTag(value)}
                    className={clsx(
                      'rounded-md border px-3 py-1 text-ui-xs',
                      tag === value
                        ? 'border-primary bg-primary text-white'
                        : 'border-border text-text hover:bg-bg-hover',
                    )}
                  >
                    {t(tagLabelKey(value))}
                  </button>
                ))}
              </div>
            </div>
            <label className="block space-y-1">
              <span className="text-ui-sm text-muted">{t('feedback.hub.new.title_label')}</span>
              <input
                data-testid="feedback-new-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t('feedback.hub.new.title.placeholder')}
                className="w-full rounded-md border border-border bg-bg px-3 py-2 text-ui-sm text-text placeholder:text-muted"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-ui-sm text-muted">{t('feedback.hub.new.body_label')}</span>
              <textarea
                data-testid="feedback-new-body"
                rows={8}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder={t('feedback.hub.new.body.placeholder')}
                className="w-full resize-none rounded-md border border-border bg-bg px-3 py-2 text-ui-sm text-text placeholder:text-muted"
              />
            </label>
            {localError && (
              <p role="alert" className="text-ui-sm text-danger">
                {localError}
              </p>
            )}
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="feedback-new-submit"
                disabled={!title.trim() || loading.create}
                onClick={() => void handleCreate()}
                className="rounded-md bg-primary px-3 py-1.5 text-ui-sm text-white hover:opacity-90 disabled:opacity-50"
              >
                {loading.create ? t('feedback.hub.loading') : t('feedback.hub.new.submit')}
              </button>
              <button
                type="button"
                data-testid="feedback-new-cancel"
                onClick={() => {
                  setCreating(false);
                  setTitle('');
                  setBody('');
                  setTag('other');
                }}
                className="rounded-md border border-border px-3 py-1.5 text-ui-sm text-text hover:bg-bg-hover"
              >
                {t('feedback.hub.new.cancel')}
              </button>
            </div>
          </div>
        ) : !currentId ? (
          <div className="flex flex-1 items-center justify-center px-6 text-ui-sm text-muted">
            {t('feedback.hub.empty_detail')}
          </div>
        ) : detailLoading && !detail ? (
          <div className="flex flex-1 items-center justify-center text-ui-sm text-muted">
            {t('feedback.hub.loading')}
          </div>
        ) : detailError ? (
          <div
            role="alert"
            className="flex flex-1 items-center justify-center text-ui-sm text-danger"
          >
            {detailError}
          </div>
        ) : detail ? (
          <>
            <header className="flex items-center gap-3 border-b border-border bg-surface px-4 py-2">
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-ui-sm font-semibold text-ink">
                  {detail.conversation.title}
                </h2>
                <p className="text-ui-2xs text-muted">
                  {formatTimestamp(detail.conversation.created_at)} ·{' '}
                  {t(statusLabelKey(detail.conversation.status))} ·{' '}
                  {t(tagLabelKey(detail.conversation.tag))}
                </p>
              </div>
              <button
                type="button"
                data-testid="feedback-toggle-status"
                onClick={() => void handleToggleStatus()}
                className="shrink-0 rounded border border-border px-2 py-1 text-ui-xs text-text hover:bg-bg-hover"
              >
                {detail.conversation.status === 'resolved'
                  ? t('feedback.hub.reopen')
                  : t('feedback.hub.mark_resolved')}
              </button>
              <button
                type="button"
                data-testid="feedback-diagnostics-toggle"
                onClick={handleToggleLog}
                className="shrink-0 rounded border border-border px-2 py-1 text-ui-xs text-text hover:bg-bg-hover"
              >
                {t('feedback.hub.diagnostics')}
              </button>
            </header>

            {showLog && (
              <div className="max-h-48 overflow-y-auto border-b border-border bg-bg-muted px-4 py-2">
                <div className="flex items-center justify-between">
                  <span className="text-ui-xs text-muted">{t('feedback.hub.diagnostics')}</span>
                  <button
                    type="button"
                    onClick={() => void refreshLogTail()}
                    className="text-ui-xs text-text underline"
                  >
                    {t('feedback.hub.diagnostics.show')}
                  </button>
                </div>
                <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-ui-2xs text-text">
                  {logTail ?? ''}
                </pre>
              </div>
            )}

            <div
              ref={streamRef}
              className="min-h-0 flex-1 space-y-2 overflow-y-auto px-4 py-3"
              data-testid="feedback-message-stream"
            >
              {messages.length === 0 ? (
                <p className="text-ui-sm text-muted">{t('feedback.hub.empty_detail')}</p>
              ) : (
                messages.map((m) => {
                  const isUser = m.role !== 'admin';
                  return (
                    <div
                      key={m.id}
                      className={clsx('flex', isUser ? 'justify-end' : 'justify-start')}
                    >
                      <div
                        className={clsx(
                          'max-w-xl rounded-lg border px-3 py-2',
                          isUser
                            ? 'border-primary bg-primary text-white'
                            : 'border-border bg-ui-panel text-text',
                        )}
                      >
                        <div className="flex items-center gap-2 text-ui-2xs opacity-80">
                          <span>
                            {isUser ? t('feedback.hub.role.user') : t('feedback.hub.role.admin')}
                          </span>
                          <span>{formatTimestamp(m.created_at)}</span>
                        </div>
                        {m.body && (
                          <p className="mt-1 whitespace-pre-wrap break-words text-ui-sm">
                            {m.body}
                          </p>
                        )}
                        {m.media_ids.length > 0 && (
                          <p className="mt-1 text-ui-2xs opacity-80">
                            {attachmentCount(m.media_ids.length)}
                          </p>
                        )}
                        {isUser && (
                          <p className="mt-1 text-ui-2xs opacity-70">
                            {m.synced_at ? t('feedback.hub.delivered') : t('feedback.hub.pending')}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            <footer className="space-y-2 border-t border-border bg-surface p-3">
              {localError && (
                <p role="alert" className="text-ui-sm text-danger">
                  {localError}
                </p>
              )}
              {pendingMediaIds.length > 0 && (
                <div className="flex items-center gap-2 text-ui-xs text-muted">
                  <span>{attachmentCount(pendingMediaIds.length)}</span>
                  <button
                    type="button"
                    onClick={() => setPendingMediaIds([])}
                    className="underline"
                  >
                    {t('feedback.hub.remove_attachment')}
                  </button>
                </div>
              )}
              <div className="flex items-end gap-2">
                <textarea
                  data-testid="feedback-composer"
                  rows={2}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={t('feedback.hub.composer.placeholder')}
                  className="flex-1 resize-none rounded-md border border-border bg-bg px-3 py-2 text-ui-sm text-text placeholder:text-muted"
                />
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={(e) => void handleAttach(e)}
                />
                <button
                  type="button"
                  data-testid="feedback-attach"
                  title={t('feedback.hub.attach.hint')}
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                  className="rounded-md border border-border px-3 py-2 text-ui-sm text-text hover:bg-bg-hover disabled:opacity-50"
                >
                  {uploading ? t('feedback.hub.uploading') : t('feedback.hub.attach')}
                </button>
                <button
                  type="button"
                  data-testid="feedback-send"
                  disabled={loading.send || (!draft.trim() && pendingMediaIds.length === 0)}
                  onClick={() => void handleSend()}
                  className="rounded-md bg-primary px-3 py-2 text-ui-sm text-white hover:opacity-90 disabled:opacity-50"
                >
                  {t('feedback.hub.send')}
                </button>
              </div>
            </footer>
          </>
        ) : null}
      </section>
    </div>
  );
}
