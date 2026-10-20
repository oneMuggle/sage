/**
 * R17-A2: 压缩谱系「查看归档」弹窗。
 *
 * 打开时拉取 GET /sessions/{id}/lineage（压缩前缀派生的归档会话，新→旧），
 * 点选某条归档后懒加载其消息（GET /sessions/{id}/messages），MessageList 只读渲染。
 *
 * 复用系统弹窗遮罩/过渡的样式基线（与 shared/ui/Modal 一致），但面板加宽到
 * max-w-2xl 以容纳消息气泡；不直接复用 Modal 因为其固定 max-w-md。
 */
import { Dialog, Transition } from '@headlessui/react';
import { Archive, X } from 'lucide-react';
import { Fragment, useCallback, useEffect, useState } from 'react';

import { sessionApi, type LineageArchive } from '../../shared/api';
import type { Message as MessageType } from '../../shared/lib/store';
import { MessageList } from '../chat/MessageList';

interface ArchivesModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** 当前会话 ID；null 时不拉取 */
  sessionId: string | null;
}

function formatTime(value: LineageArchive['archived_at']): string {
  if (value == null) return '—';
  const ts = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(ts) || ts <= 0) return String(value);
  return new Date(ts).toLocaleString();
}

export function ArchivesModal({ isOpen, onClose, sessionId }: ArchivesModalProps) {
  const [archives, setArchives] = useState<LineageArchive[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<LineageArchive | null>(null);
  const [messages, setMessages] = useState<MessageType[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const [copiedItemId, setCopiedItemId] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !sessionId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelected(null);
    setMessages([]);
    setArchives([]);
    sessionApi
      .getLineage(sessionId)
      .then((lineage) => {
        if (!cancelled) setArchives(lineage.archives ?? []);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, sessionId]);

  const openArchive = useCallback(async (archive: LineageArchive) => {
    setSelected(archive);
    setMessages([]);
    setMessagesLoading(true);
    try {
      setMessages(await sessionApi.getMessages(archive.archive_session_id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setMessagesLoading(false);
    }
  }, []);

  /* v8 ignore start */
  const handleCopyMd = async () => {
    const lines = selected
      ? [
          `# 压缩归档: ${selected.title}`,
          '',
          `- **归档 ID**: \`${selected.archive_session_id}\``,
          `- **消息数**: ${selected.message_count}`,
          '',
          ...messages.map(
            (m) =>
              `### ${m.role}\n\n${typeof m.content === 'string' ? m.content : JSON.stringify(m.content)}`,
          ),
        ]
      : [
          '# 会话压缩归档列表',
          '',
          `- **归档总数**: ${archives.length}`,
          '',
          ...archives.map(
            (a) =>
              `- **${a.title}** (\`${a.archive_session_id}\`) · ${a.message_count} 条 · ${formatTime(a.archived_at)}`,
          ),
        ];
    setCopiedMd(true);
    await navigator.clipboard?.writeText(lines.join('\n'));
    setTimeout(() => setCopiedMd(false), 1800);
  };

  const handleCopyJson = async () => {
    const payload = selected ? { archive: selected, messages } : { sessionId, archives };
    setCopiedJson(true);
    await navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    setTimeout(() => setCopiedJson(false), 1800);
  };

  const handleCopyItemJson = async (e: React.MouseEvent, archive: LineageArchive) => {
    e.stopPropagation();
    setCopiedItemId(archive.archive_session_id);
    await navigator.clipboard?.writeText(JSON.stringify(archive, null, 2));
    setTimeout(
      () => setCopiedItemId((prev) => (prev === archive.archive_session_id ? null : prev)),
      1800,
    );
  };
  /* v8 ignore stop */

  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-overlay" />
        </Transition.Child>

        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-200"
              enterFrom="opacity-0 scale-95"
              enterTo="opacity-100 scale-100"
              leave="ease-in duration-150"
              leaveFrom="opacity-100 scale-100"
              leaveTo="opacity-0 scale-95"
            >
              <Dialog.Panel className="w-full max-w-2xl transform overflow-hidden rounded-xl bg-surface-elevated dark:bg-surface shadow-xl transition-all">
                <div className="flex items-center justify-between px-6 py-4 border-b border-border">
                  <Dialog.Title as="h3" className="text-lg font-semibold">
                    压缩归档
                  </Dialog.Title>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      data-testid="archives-modal-copy-md-btn"
                      disabled={!selected && archives.length === 0}
                      onClick={() => void handleCopyMd()}
                      className="px-2 py-0.5 text-xs rounded border border-border text-muted hover:text-text hover:bg-bg-subtle disabled:opacity-50"
                    >
                      {copiedMd ? '✓ 已复制MD' : '复制归档MD'}
                    </button>
                    <button
                      type="button"
                      data-testid="archives-modal-copy-json-btn"
                      disabled={!selected && archives.length === 0}
                      onClick={() => void handleCopyJson()}
                      className="px-2 py-0.5 text-xs rounded border border-border text-muted hover:text-text hover:bg-bg-subtle disabled:opacity-50"
                    >
                      {copiedJson ? '✓ 已复制JSON' : '复制归档JSON'}
                    </button>
                    <button
                      type="button"
                      onClick={onClose}
                      aria-label="关闭归档弹窗"
                      className="p-1 rounded text-muted hover:text-text hover:bg-bg-subtle transition-colors"
                    >
                      <X className="w-5 h-5" />
                    </button>
                  </div>
                </div>

                <div className="px-6 py-4 max-h-[70vh] overflow-y-auto">
                  {error && (
                    <div role="alert" className="mb-3 p-2 rounded bg-error/10 text-error text-sm">
                      {error}
                    </div>
                  )}
                  {loading && <p className="text-sm text-muted">加载归档列表...</p>}

                  {!loading && !selected && (
                    <div className="flex flex-col gap-2">
                      {archives.length === 0 && !error && (
                        <p className="text-sm text-muted">该会话暂无压缩归档</p>
                      )}
                      {archives.map((archive) => (
                        <button
                          key={archive.archive_session_id}
                          type="button"
                          onClick={() => openArchive(archive)}
                          data-testid="archive-entry"
                          className="flex items-center justify-between gap-3 p-2.5 rounded-radius-sm border border-border hover:bg-bg-subtle transition-colors text-left"
                        >
                          <span className="flex items-center gap-2 min-w-0">
                            <Archive className="w-4 h-4 text-muted flex-shrink-0" />
                            <span className="text-sm text-text truncate">{archive.title}</span>
                          </span>
                          <span className="text-xs text-muted flex-shrink-0 flex items-center gap-2">
                            <span>
                              {archive.message_count} 条 · {formatTime(archive.archived_at)}
                            </span>
                            <span
                              role="button"
                              tabIndex={0}
                              data-testid={`archive-item-copy-json-${archive.archive_session_id}`}
                              onClick={(e) => void handleCopyItemJson(e, archive)}
                              className="px-1.5 py-0.5 rounded border border-border text-ui-2xs hover:text-text"
                            >
                              {copiedItemId === archive.archive_session_id ? '✓ 已复制' : '复制JSON'}
                            </span>
                          </span>
                        </button>
                      ))}
                    </div>
                  )}

                  {selected && (
                    <div>
                      <button
                        type="button"
                        onClick={() => setSelected(null)}
                        className="mb-3 text-xs text-muted hover:text-text transition-colors"
                      >
                        ← 返回归档列表
                      </button>
                      {messagesLoading ? (
                        <p className="text-sm text-muted">加载归档消息...</p>
                      ) : (
                        <MessageList messages={messages} />
                      )}
                    </div>
                  )}
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}
