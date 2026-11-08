/**
 * 新建群聊对话框（M2 私聊/群聊）。
 *
 * 多选已启用的专家 → 调用 store.createSession(participantIds, 'group')
 * 创建群聊会话 → 回调 onCreated(sessionId)（父组件跳转 /chat）。
 */
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { agentsApi, type AgentProfile } from '../../shared/api';
import { useStore } from '../../shared/lib/store';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';

interface GroupChatDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 群聊创建成功（导航由父组件负责）。 */
  onCreated: (sessionId: string) => void;
}

function readAvatar(agent: AgentProfile): string {
  const ui = agent.persona_ui as Record<string, unknown> | undefined;
  const avatar = ui?.avatar;
  return typeof avatar === 'string' && avatar.trim() ? avatar.trim() : '🤖';
}

export function GroupChatDialog({ open, onOpenChange, onCreated }: GroupChatDialogProps) {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSelected(new Set());
    setLoading(true);
    let cancelled = false;
    agentsApi
      .list()
      .then((list) => {
        if (!cancelled) {
          setAgents(list.filter((agent) => agent.role === 'specialist' && agent.enabled));
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          toast.error(`加载专家失败：${err instanceof Error ? err.message : String(err)}`);
          setAgents([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  function toggle(agentId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  }

  async function handleCreate() {
    if (selected.size < 2) {
      toast.error('请至少选择 2 位专家');
      return;
    }
    setSaving(true);
    try {
      const names = agents.filter((agent) => selected.has(agent.id)).map((agent) => agent.name);
      const sessionId = await useStore.getState().createSession(false, {
        title: `群聊（${names.join(' + ')}）`,
        participantIds: Array.from(selected),
        conversationType: 'group',
      });
      toast.success('群聊已创建');
      onCreated(sessionId);
      onOpenChange(false);
    } catch (err) {
      toast.error(`创建群聊失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>新建群聊</DialogTitle>
          <DialogDescription>
            选择多位专家进入同一个会话。对话中用 @专家名 指定由谁回答，未指定时由主持专家回答。
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 max-h-80 overflow-y-auto">
          {loading ? (
            <p className="py-6 text-center text-sm text-muted">加载专家…</p>
          ) : agents.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted">
              没有已启用的专家，请先创建或启用专家。
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {agents.map((agent) => (
                <li key={agent.id}>
                  <label
                    className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 transition-colors ${
                      selected.has(agent.id)
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:bg-bg-hover'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(agent.id)}
                      onChange={() => toggle(agent.id)}
                      className="h-4 w-4"
                    />
                    <span className="text-xl" aria-hidden="true">
                      {readAvatar(agent)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{agent.name}</span>
                      <span className="block truncate text-ui-xs text-muted">
                        {agent.description || '暂无标语'}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            取消
          </Button>
          <Button onClick={() => void handleCreate()} disabled={saving || selected.size < 2}>
            {saving ? '创建中…' : `创建群聊（${selected.size}）`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
