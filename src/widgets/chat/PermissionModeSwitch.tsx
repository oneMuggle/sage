// src/widgets/chat/PermissionModeSwitch.tsx
//
// 对标 S3 (2026-09-13, 竞品对标 §2.3): 聊天顶栏权限三档一键切换 + 本会话
// "已自动批准 N 次"徽记 + 审计弹层。对标 Claude Code / Cursor 的权限模式。
//
// 三档映射到后端既有 permission_mode（见 permissionApi），切换即写设置，
// 下一次工具调用起生效（enforcer 在每次 run 起点构造）。
// 计数来源: GET /permissions/session/{id}/auto-approvals，流结束跳变 + 30s 轮询。

import { ChevronDown, ShieldAlert, ShieldCheck, ShieldHalf, Zap } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useChatStreamStore, selectSessionSlots } from '../../features/send-message/chatStreamStore';
import {
  PERMISSION_PRESETS,
  permissionApi,
  type AutoApprovalRecord,
  type PermissionPreset,
} from '../../shared/api/permissionApi';
import { useI18n } from '../../shared/lib/i18n';

const PRESET_ICON = {
  careful: ShieldAlert,
  standard: ShieldHalf,
  auto: Zap,
} as const;

interface PermissionModeSwitchProps {
  sessionId: string | null;
}

function formatTime(ts: number): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

export function PermissionModeSwitch({ sessionId }: PermissionModeSwitchProps) {
  const { t } = useI18n();
  const [preset, setPreset] = useState<PermissionPreset>('standard');
  const [custom, setCustom] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [count, setCount] = useState(0);
  const [items, setItems] = useState<AutoApprovalRecord[]>([]);
  const rootRef = useRef<HTMLDivElement>(null);

  const streamingMessageId = useChatStreamStore((s) =>
    selectSessionSlots(s, sessionId).streaming?.messageId ?? null,
  );
  const prevStreamingIdRef = useRef<string | null>(null);

  useEffect(() => {
    permissionApi
      .getPreset()
      .then((s) => {
        setPreset(s.preset);
        setCustom(s.custom);
      })
      .catch(() => undefined);
  }, []);

  const loadAudit = useCallback((sid: string | null) => {
    if (!sid) {
      setCount(0);
      setItems([]);
      return;
    }
    void permissionApi.getSessionAutoApprovals(sid).then((res) => {
      setCount(res.count);
      setItems(res.items.slice().reverse());
    });
  }, []);

  useEffect(() => {
    loadAudit(sessionId);
    if (!sessionId) return;
    const timer = window.setInterval(() => loadAudit(sessionId), 30_000);
    return () => window.clearInterval(timer);
  }, [sessionId, loadAudit]);

  useEffect(() => {
    const prev = prevStreamingIdRef.current;
    prevStreamingIdRef.current = streamingMessageId;
    if (prev !== null && streamingMessageId === null && sessionId) loadAudit(sessionId);
  }, [streamingMessageId, sessionId, loadAudit]);

  // 点击外部关闭
  useEffect(() => {
    if (!menuOpen && !auditOpen) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
        setAuditOpen(false);
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [menuOpen, auditOpen]);

  const choose = async (next: PermissionPreset) => {
    setMenuOpen(false);
    if (next === preset && !custom) return;
    const prevPreset = preset;
    setPreset(next);
    setCustom(false);
    try {
      await permissionApi.setPreset(next);
      toast.success(t(`chat.perm.${next}`) + ' · ' + t('chat.perm.applied'));
    } catch {
      setPreset(prevPreset);
      toast.error(t('chat.perm.failed'));
    }
  };

  const Icon = PRESET_ICON[preset];

  return (
    <div ref={rootRef} className="relative flex items-center gap-1" data-testid="permission-mode-switch">
      <button
        type="button"
        onClick={() => {
          setMenuOpen((v) => !v);
          setAuditOpen(false);
        }}
        title={t(`chat.perm.${preset}.desc`)}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        data-testid="permission-mode-button"
        className="flex items-center gap-1 px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
      >
        <Icon className="w-3.5 h-3.5" aria-hidden />
        <span>{t(`chat.perm.${preset}`)}</span>
        {custom && <span className="text-[10px] text-text-secondary">({t('chat.perm.custom')})</span>}
        <ChevronDown className="w-3 h-3 opacity-60" aria-hidden />
      </button>

      {sessionId && count > 0 && (
        <button
          type="button"
          onClick={() => {
            setAuditOpen((v) => !v);
            setMenuOpen(false);
          }}
          title={t('chat.perm.audit_title')}
          data-testid="auto-approval-badge"
          className="flex items-center gap-1 px-1.5 py-1 text-[11px] rounded-radius-sm border border-border text-text-secondary hover:bg-bg-hover"
        >
          <ShieldCheck className="w-3 h-3 text-accent" aria-hidden />
          {t('chat.perm.auto_count').replace('{n}', String(count))}
        </button>
      )}

      {menuOpen && (
        <div
          role="menu"
          data-testid="permission-mode-menu"
          className="absolute right-0 top-full mt-1 z-30 w-64 rounded border border-border bg-surface shadow-lg p-1"
        >
          {PERMISSION_PRESETS.map((p) => {
            const PIcon = PRESET_ICON[p];
            const active = p === preset && !custom;
            return (
              <button
                key={p}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                data-testid={`permission-preset-${p}`}
                onClick={() => void choose(p)}
                className={`w-full text-left flex items-start gap-2 px-2 py-1.5 rounded text-xs hover:bg-bg-hover ${
                  active ? 'bg-primary/10 text-primary' : 'text-text'
                }`}
              >
                <PIcon className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden />
                <span className="min-w-0">
                  <span className="block font-medium">{t(`chat.perm.${p}`)}</span>
                  <span className="block text-[11px] text-text-secondary">{t(`chat.perm.${p}.desc`)}</span>
                </span>
              </button>
            );
          })}
          <p className="px-2 pt-1 text-[10px] text-text-secondary border-t border-border mt-1">
            {t('chat.perm.destructive_note')}
          </p>
        </div>
      )}

      {auditOpen && (
        <div
          data-testid="auto-approval-audit"
          className="absolute right-0 top-full mt-1 z-30 w-80 max-h-72 overflow-y-auto rounded border border-border bg-surface shadow-lg p-2"
        >
          <p className="text-xs font-semibold text-text mb-1">{t('chat.perm.audit_title')}</p>
          {items.length === 0 ? (
            <p className="text-xs text-text-secondary">{t('chat.perm.audit_empty')}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border">
              {items.map((it) => (
                <li key={it.seq} className="py-1.5 text-xs" data-testid="auto-approval-item">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-text">{it.tool_name}</span>
                    <span className="px-1 rounded bg-bg-hover text-[10px] text-text-secondary">{it.capability}</span>
                    <span className="ml-auto text-[10px] text-text-secondary">{formatTime(it.created_at)}</span>
                  </div>
                  {it.summary && (
                    <p className="text-text-secondary truncate" title={it.summary}>
                      {it.summary}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
