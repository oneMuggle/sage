// src/features/feedback/FeedbackHub.tsx
//
// 用户反馈会话页：左侧会话列表，右侧消息流 + 输入框。
// 管理员回复由 Electron 主进程的 FeedbackSyncer 拉取后落进本地 SQLite，
// 这里只读本地数据（经 feedbackStore），不直接访问管理员地址。
//
// 设计见 docs/plans/2026-10-29_direct-feedback-channel.md §4。

import { clsx } from 'clsx';
import { useEffect, useRef, useState, type ChangeEvent } from 'react';

import { uploadAttachment } from '../../shared/api/feedbackApi';
import { useI18n } from '../../shared/lib/i18n';

import { useFeedbackStore } from './feedbackStore';

const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;

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

function statusLabelKey(status: string): FeedbackStatusKey {
  if (status === 'resolved') return 'feedback.hub.status.resolved';
  if (status === 'closed') return 'feedback.hub.status.closed';
  return 'feedback.hub.status.open';
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
  const [draft, setDraft] = useState('');
  const [pendingMediaIds, setPendingMediaIds] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const detail = currentId ? detailById[currentId] : undefined;
  const messages = detail?.messages ?? [];
  const detailLoading = currentId ? loading.detail[currentId] : false;
  const detailError = currentId ? errors.detail[currentId] : null;

  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [currentId, messages.length]);

  const handleCreate = async (): Promise<void> => {
    if (!title.trim() || loading.create) return;
    setLocalError(null);
    const id = await createAndOpen({ title: title.trim(), body: body.trim() });
    if (id) {
      setTitle('');
      setBody('');
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

        <div className="min-h-0 flex-1 overflow-y-auto">
          {conversations.length === 0 ? (
            <p className="px-3 py-3 text-ui-xs text-muted">
              {loading.list ? t('feedback.hub.loading') : t('feedback.hub.list.empty')}
            </p>
          ) : (
            conversations.map((c) => (
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
                <span className="mt-0.5 block text-ui-2xs text-muted">
                  {formatTimestamp(c.last_activity_at)}
                </span>
              </button>
            ))
          )}
        </div>

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
                  {t(statusLabelKey(detail.conversation.status))}
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
