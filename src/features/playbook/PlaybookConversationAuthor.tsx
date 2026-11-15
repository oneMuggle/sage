/**
 * PlaybookConversationAuthor — 对话式 AI 规程定制面板（2026-11-14）。
 *
 * 与一次性 PlaybookAuthorPanel 的区别：
 * - 多轮对话迭代阶段草案，每轮可回退到上一版；
 * - 可从项目目录 / git 历史推断阶段，作为有依据的起点；
 * - 只有「确认绑定」才落库，推断结果不自动生效。
 */
import { useEffect, useState } from 'react';

import {
  type PlaybookConversation,
  type PlaybookStageInference,
  playbookApi,
} from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

import { usePlaybookI18n } from './usePlaybookI18n';

export interface PlaybookConversationAuthorProps {
  projectId: string;
  onBound: () => void;
  onNotice: (message: string) => void;
  onError: (message: string) => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function PlaybookConversationAuthor({
  projectId,
  onBound,
  onNotice,
  onError,
}: PlaybookConversationAuthorProps) {
  const { t, tf } = usePlaybookI18n();
  const [open, setOpen] = useState(false);
  const [conversation, setConversation] = useState<PlaybookConversation | null>(null);
  const [inference, setInference] = useState<PlaybookStageInference | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    setConversation(null);
    setInference(null);
    setInput('');
    setBusy(null);
  }, [projectId]);

  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    try {
      await action();
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const handleStart = () =>
    run('start', async () => {
      const data = await playbookApi.startAuthorConversation(projectId);
      setConversation(data);
    });

  const handleSend = () => {
    const text = input.trim();
    if (!conversation || !text) return;
    void run('send', async () => {
      const turn = await playbookApi.sendAuthorMessage(projectId, conversation.id, text);
      setConversation(turn.conversation);
      setInput('');
      if (turn.source === 'deterministic') {
        onNotice(t('playbook.conversation.fallback'));
      }
    });
  };

  const handleRollback = () => {
    if (!conversation) return;
    const assistantTurns = conversation.messages
      .filter((message) => message.role === 'assistant')
      .map((message) => message.turn_index);
    const target = (assistantTurns.length ? Math.max(...assistantTurns) : 0) - 1;
    if (target < 0) return;
    void run('rollback', async () => {
      const result = await playbookApi.rollbackAuthorConversation(
        projectId,
        conversation.id,
        target,
      );
      setConversation(result.conversation);
    });
  };

  const handleCommit = () => {
    if (!conversation) return;
    void run('commit', async () => {
      const result = await playbookApi.commitAuthorConversation(projectId, conversation.id);
      setConversation(result.conversation);
      onNotice(tf('playbook.conversation.committed', { version: result.snapshot.version }));
      onBound();
    });
  };

  const handleInfer = () =>
    run('infer', async () => {
      const result = await playbookApi.inferStages(projectId);
      setInference(result);
    });

  const handleBindInferred = () => {
    const spec = inference?.playbook;
    if (!spec) return;
    void run('bind-inferred', async () => {
      await playbookApi.bind(projectId, { spec, source: 'inferred' });
      onNotice(t('playbook.infer.bound'));
      onBound();
    });
  };

  const messages = conversation?.messages ?? [];
  const stages = conversation?.current_spec?.stages ?? [];
  const committed = conversation?.status === 'committed';
  const assistantTurns = messages
    .filter((message) => message.role === 'assistant')
    .map((message) => message.turn_index);
  const canRollback = !committed && assistantTurns.length > 0;

  return (
    <div className="space-y-2">
      <Button
        size="sm"
        variant="secondary"
        onClick={() => setOpen((value) => !value)}
        data-testid="playbook-conversation-toggle"
      >
        {open ? t('playbook.conversation.toggleClose') : t('playbook.conversation.toggle')}
      </Button>
      {open && (
        <div className="space-y-2 rounded-md border border-border p-2">
          <div className="text-xs text-muted-foreground">{t('playbook.conversation.hint')}</div>
          {!conversation ? (
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="primary"
                onClick={() => void handleStart()}
                disabled={busy !== null}
                data-testid="playbook-conversation-start"
              >
                {busy === 'start'
                  ? t('playbook.conversation.starting')
                  : t('playbook.conversation.start')}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void handleInfer()}
                disabled={busy !== null}
                data-testid="playbook-infer-btn"
              >
                {busy === 'infer' ? t('playbook.infer.running') : t('playbook.infer.button')}
              </Button>
            </div>
          ) : (
            <>
              <div
                className="max-h-56 space-y-1.5 overflow-y-auto pr-1"
                data-testid="playbook-conversation-messages"
              >
                {messages.map((message, index) => (
                  <div
                    key={`${message.turn_index}-${index}`}
                    className={message.role === 'user' ? 'text-right' : 'text-left'}
                  >
                    <div
                      className={
                        message.role === 'user'
                          ? 'inline-block max-w-full whitespace-pre-wrap rounded-md bg-primary/10 px-2 py-1 text-xs text-foreground'
                          : 'inline-block max-w-full whitespace-pre-wrap rounded-md bg-muted/60 px-2 py-1 text-xs text-foreground'
                      }
                    >
                      {message.content}
                    </div>
                  </div>
                ))}
              </div>
              <div className="space-y-1" data-testid="playbook-conversation-stages">
                {stages.length ? (
                  stages.map((stage, index) => (
                    <div
                      key={`${stage.id}-${index}`}
                      className="flex items-center justify-between text-xs"
                    >
                      <span className="text-foreground">
                        {index + 1}. {stage.label}
                      </span>
                      <span className="text-muted-foreground">
                        {tf('playbook.conversation.stageMeta', {
                          count: stage.artifacts.length,
                        })}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="text-xs text-muted-foreground">
                    {t('playbook.conversation.emptyStages')}
                  </div>
                )}
              </div>
              {!committed && (
                <div className="space-y-1">
                  <textarea
                    value={input}
                    onChange={(event) => setInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        handleSend();
                      }
                    }}
                    aria-label={t('playbook.conversation.inputPlaceholder')}
                    placeholder={t('playbook.conversation.inputPlaceholder')}
                    rows={2}
                    className="w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
                    data-testid="playbook-conversation-input"
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={handleSend}
                      disabled={busy !== null || !input.trim()}
                      data-testid="playbook-conversation-send"
                    >
                      {busy === 'send'
                        ? t('playbook.conversation.sending')
                        : t('playbook.conversation.send')}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={handleRollback}
                      disabled={busy !== null || !canRollback}
                      data-testid="playbook-conversation-rollback"
                    >
                      {t('playbook.conversation.rollback')}
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={handleCommit}
                      disabled={busy !== null || !stages.length}
                      data-testid="playbook-conversation-commit"
                    >
                      {busy === 'commit'
                        ? t('playbook.conversation.committing')
                        : t('playbook.conversation.commit')}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void handleInfer()}
                      disabled={busy !== null}
                      data-testid="playbook-infer-btn"
                    >
                      {busy === 'infer' ? t('playbook.infer.running') : t('playbook.infer.button')}
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
          {inference && (
            <div
              className="space-y-1 rounded-md bg-muted/40 p-2 text-xs"
              data-testid="playbook-infer-result"
            >
              <div className="font-medium text-foreground">
                {tf('playbook.infer.title', {
                  confidence: Math.round(inference.confidence * 100),
                })}
              </div>
              <div className="text-muted-foreground">{inference.rationale}</div>
              {inference.stages.length ? (
                <ul className="list-disc pl-4 text-foreground">
                  {inference.stages.map((stage, index) => (
                    <li key={`${stage.label}-${index}`}>{stage.label}</li>
                  ))}
                </ul>
              ) : (
                <div className="text-muted-foreground">{t('playbook.infer.empty')}</div>
              )}
              {inference.playbook && (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={handleBindInferred}
                  disabled={busy !== null}
                  data-testid="playbook-bind-inferred"
                >
                  {busy === 'bind-inferred'
                    ? t('playbook.infer.binding')
                    : t('playbook.infer.bind')}
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default PlaybookConversationAuthor;
