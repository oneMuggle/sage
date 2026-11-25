/**
 * RuleRefinePanel — natural-language refinement of the extraction draft.
 *
 * The user types an instruction ("加上参考文献 GB/T 7714 要求"、"行间距改成1.5倍"),
 * the backend LLM proposes structured actions, and each action is shown as an
 * accept/reject diff card. Accepted actions are applied to the draft store;
 * nothing touches the database until the draft is committed.
 */

import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { officeRulesApi } from '../../../shared/api/officeRulesApi';
import type { WireRefineAction, WireRefineDraftRule } from '../../../shared/api/types';

import { RuleDiffCard } from './RuleDiffCard';
import { useRuleDraftStore } from './ruleDraftStore';

interface ChatEntry {
  id: number;
  role: 'user' | 'assistant' | 'system';
  text: string;
  actions?: { action: WireRefineAction; resolved: boolean }[];
}

let _entryId = 0;
function nextEntryId(): number {
  _entryId += 1;
  return _entryId;
}

export function RuleRefinePanel() {
  const rules = useRuleDraftStore((state) => state.rules);
  const applyRefineAction = useRuleDraftStore((state) => state.applyRefineAction);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    requestAnimationFrame(() => {
      const el = listRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    });
  };

  const handleSend = async () => {
    const instruction = input.trim();
    if (!instruction || busy) return;
    setInput('');
    setBusy(true);
    const userEntry: ChatEntry = { id: nextEntryId(), role: 'user', text: instruction };
    setEntries((prev) => [...prev, userEntry]);
    scrollToBottom();

    try {
      const wireRules: WireRefineDraftRule[] = rules.map((r) => ({
        temp_id: r.tempId,
        name: r.name,
        kind: r.kind,
        params: r.params,
        severity: r.severity,
        description: r.description,
        ai_prompt: r.suggestedAiPrompt,
        type: r.suggestedType,
        scope: r.suggestedScope,
      }));
      const result = await officeRulesApi.refineRules({
        instruction,
        rules: wireRules,
      });
      const warnText = result.warnings.map((w) => w.message).join('；');
      const assistantEntry: ChatEntry = {
        id: nextEntryId(),
        role: 'assistant',
        text: warnText,
        actions: result.actions.map((action) => ({ action, resolved: false })),
      };
      setEntries((prev) => [...prev, assistantEntry]);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      setEntries((prev) => [
        ...prev,
        { id: nextEntryId(), role: 'system', text: `AI 精炼失败: ${message}` },
      ]);
    } finally {
      setBusy(false);
      scrollToBottom();
    }
  };

  const resolveAction = (entryId: number, actionIndex: number, accept: boolean) => {
    const entry = entries.find((item) => item.id === entryId);
    const target = entry?.actions?.[actionIndex];
    if (!target || target.resolved) return;
    if (accept) {
      applyRefineAction(target.action);
    }
    setEntries((prev) =>
      prev.map((item) => {
        if (item.id !== entryId || !item.actions) return item;
        return {
          ...item,
          actions: item.actions.map((actionItem, index) =>
            index === actionIndex ? { ...actionItem, resolved: true } : actionItem,
          ),
        };
      }),
    );
    if (accept) {
      toast.success('已应用到草稿');
    }
  };

  const acceptAll = (entryId: number) => {
    const entry = entries.find((item) => item.id === entryId);
    if (!entry?.actions) return;
    entry.actions.forEach((item) => {
      if (!item.resolved && item.action.type !== 'explain') {
        applyRefineAction(item.action);
      }
    });
    setEntries((prev) =>
      prev.map((item) => {
        if (item.id !== entryId || !item.actions) return item;
        return {
          ...item,
          actions: item.actions.map((actionItem) => ({ ...actionItem, resolved: true })),
        };
      }),
    );
  };

  return (
    <div className="flex h-full flex-col" data-testid="rule-refine-panel">
      <div className="border-b border-border px-3 py-2">
        <div className="text-xs font-semibold">💬 AI 精炼</div>
        <div className="text-[11px] text-muted">
          用自然语言增删改规则，每条建议需你确认后才会应用。
        </div>
      </div>

      <div ref={listRef} className="flex-1 space-y-2 overflow-y-auto px-3 py-2">
        {entries.length === 0 && (
          <div className="space-y-1 text-[11px] text-muted">
            <div>试试这些指令：</div>
            <div>· 加上：参考文献格式采用 GB/T 7714</div>
            <div>· 行间距改成 1.5 倍行距</div>
            <div>· 去掉页边距相关的规则</div>
          </div>
        )}
        {entries.map((entry) => (
          <div key={entry.id}>
            {entry.role === 'user' ? (
              <div className="ml-6 rounded-md bg-primary/10 px-2.5 py-1.5 text-xs text-text">
                {entry.text}
              </div>
            ) : entry.role === 'system' ? (
              <div className="rounded-md bg-red-50 px-2.5 py-1.5 text-[11px] text-red-600">
                {entry.text}
              </div>
            ) : (
              <div className="space-y-1.5">
                {entry.text && (
                  <div className="rounded-md bg-yellow-50 px-2.5 py-1.5 text-[11px] text-yellow-700">
                    ⚠️ {entry.text}
                  </div>
                )}
                {entry.actions && entry.actions.length > 0 && (
                  <>
                    {entry.actions.some(
                      (item) => !item.resolved && item.action.type !== 'explain',
                    ) && (
                      <button
                        type="button"
                        onClick={() => acceptAll(entry.id)}
                        className="text-[11px] text-primary hover:underline"
                      >
                        全部接受
                      </button>
                    )}
                    {entry.actions.map((item, index) => (
                      <div key={index} className={item.resolved ? 'opacity-50' : ''}>
                        <RuleDiffCard
                          action={item.action}
                          currentRule={
                            item.action.temp_id
                              ? rules.find((r) => r.tempId === item.action.temp_id)
                              : undefined
                          }
                          onAccept={() => resolveAction(entry.id, index, true)}
                          onReject={() => resolveAction(entry.id, index, false)}
                        />
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-1.5 text-[11px] text-muted">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
            AI 思考中...
          </div>
        )}
      </div>

      <div className="border-t border-border px-2 py-2">
        <div className="flex items-end gap-1.5">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
            rows={2}
            placeholder="输入修改指令，回车发送"
            className="flex-1 resize-none rounded border border-border bg-surface px-2 py-1 text-xs"
            data-testid="rule-refine-input"
          />
          <button
            type="button"
            onClick={() => void handleSend()}
            disabled={busy || !input.trim()}
            className="rounded bg-primary px-2.5 py-1 text-xs text-white hover:bg-primary/90 disabled:opacity-50"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
