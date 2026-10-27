// src/widgets/chat/PermissionModeSwitch.tsx
//
// 对标 S3 (2026-09-13, 竞品对标 §2.3): 聊天顶栏权限三档一键切换 + 本会话
// "已自动批准 N 次"徽记 + 审计弹层。对标 Claude Code / Cursor 的权限模式。
//
// 三档映射到后端既有 permission_mode（见 permissionApi），切换即写设置，
// 下一次工具调用起生效（enforcer 在每次 run 起点构造）。
// 计数来源: GET /permissions/session/{id}/auto-approvals，流结束跳变 + 30s 轮询。
// R106: 同一徽记/弹层可查看并撤销本会话「仅本次会话记住」的规则
// (GET/POST /permissions/session/{id}/remembered-rules*)，刷新节奏与审计一致；
// 徽记在自动批准 0 次但存在会话规则时也出现（会话 deny 不产生放行记录）。
// R110: 弹层打开时取一次生命周期名单，给审计逐条标注所属插件
// （权威名结构化归属，读不到整体不标）；会话规则复用共享遮蔽
// 派生标注被同列表更高优先级规则覆盖的行。两者只读、不进导出。

import { ChevronDown, ShieldAlert, ShieldCheck, ShieldHalf, Zap } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useChatStreamStore, selectSessionSlots } from '../../features/send-message/chatStreamStore';
import {
  PERMISSION_PRESETS,
  permissionApi,
  type AutoApprovalRecord,
  type PermissionPreset,
  type PermissionRuleItem,
} from '../../shared/api/permissionApi';
import { pluginClient } from '../../shared/api/pluginClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { findPluginToolOwner, findShadowedRules } from '../../shared/lib/permissionInsights';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

const PRESET_ICON = {
  careful: ShieldAlert,
  standard: ShieldHalf,
  auto: Zap,
} as const;

interface PermissionModeSwitchProps {
  sessionId: string | null;
  placement?: 'top' | 'bottom';
}

function formatTime(ts: number): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

export function formatPermissionModeMarkdown(params: {
  sessionId: string | null;
  preset: PermissionPreset;
  custom: boolean;
  count: number;
  items: ReadonlyArray<AutoApprovalRecord>;
}): string {
  const lines = [
    '# 会话权限模式与自动放行审计 (Permission Mode Summary)',
    '',
    `- **会话 ID**: ${params.sessionId ? `\`${params.sessionId}\`` : '全局'}`,
    `- **当前权限预设**: \`${params.preset}\`${params.custom ? ' (自定义)' : ''}`,
    `- **自动放行次数**: ${params.count}`,
  ];
  if (params.items.length === 0) {
    lines.push('', '_暂无自动放行审计记录_');
  } else {
    lines.push('', '## 自动放行审计明细');
    for (const it of params.items) {
      lines.push(
        `- **${it.tool_name}** (\`${it.capability}\`, ${formatTime(it.created_at)}): ${it.summary || '-'}`,
      );
    }
  }
  return lines.join('\n');
}

export function formatPermissionModeJson(params: {
  sessionId: string | null;
  preset: PermissionPreset;
  custom: boolean;
  count: number;
  items: ReadonlyArray<AutoApprovalRecord>;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      ...params,
    },
    null,
    2,
  );
}

export function PermissionModeSwitch({ sessionId, placement = 'top' }: PermissionModeSwitchProps) {
  const popupPos = placement === 'bottom' ? 'top-full mt-1' : 'bottom-full mb-1';
  const { t } = useI18n();
  const [preset, setPreset] = useState<PermissionPreset>('standard');
  const [custom, setCustom] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [count, setCount] = useState(0);
  const [items, setItems] = useState<AutoApprovalRecord[]>([]);
  const [sessionRules, setSessionRules] = useState<PermissionRuleItem[]>([]);
  const [sessionRulesFailed, setSessionRulesFailed] = useState(false);
  const [sessionRulesBusy, setSessionRulesBusy] = useState(false);
  const [pluginNames, setPluginNames] = useState<string[] | null>(null);
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

  const loadSessionRules = useCallback((sid: string | null) => {
    if (!sid) {
      setSessionRules([]);
      setSessionRulesFailed(false);
      return;
    }
    permissionApi
      .listSessionRememberedRules(sid)
      .then((rules) => {
        setSessionRules(rules);
        setSessionRulesFailed(false);
      })
      .catch(() => setSessionRulesFailed(true));
  }, []);

  useEffect(() => {
    loadAudit(sessionId);
    loadSessionRules(sessionId);
    if (!sessionId) return;
    const timer = window.setInterval(() => {
      loadAudit(sessionId);
      loadSessionRules(sessionId);
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [sessionId, loadAudit, loadSessionRules]);

  // R110: 审计归属的数据源——只在弹层打开时取一次生命周期名单
  // （不进轮询节奏）；失败置 null 整体不标（读不到≠无归属）。
  useEffect(() => {
    if (!auditOpen) return;
    let cancelled = false;
    pluginClient
      .list()
      .then((records) => {
        if (!cancelled) setPluginNames(records.map((record) => record.name));
      })
      .catch(() => {
        if (!cancelled) setPluginNames(null);
      });
    return () => {
      cancelled = true;
    };
  }, [auditOpen]);

  // R110: 会话规则遮蔽（与持久侧 R109 同源）与审计归属派生。
  const shadowedSessionRules = findShadowedRules(sessionRules);
  const auditPluginOwners = new Map(
    items.map((it) => [it.seq, findPluginToolOwner(it.tool_name, pluginNames)] as const),
  );

  useEffect(() => {
    const prev = prevStreamingIdRef.current;
    prevStreamingIdRef.current = streamingMessageId;
    if (prev !== null && streamingMessageId === null && sessionId) {
      loadAudit(sessionId);
      loadSessionRules(sessionId);
    }
  }, [streamingMessageId, sessionId, loadAudit, loadSessionRules]);

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

  // R106 撤销一条本会话记住的决定：采用后端返回的最新列表，
  // 不在前端自行删除后假定成功；失败保留原列表并提示。
  const revokeSessionRule = async (rule: PermissionRuleItem) => {
    if (!sessionId || sessionRulesBusy) return;
    setSessionRulesBusy(true);
    try {
      setSessionRules(await permissionApi.deleteSessionRememberedRule(sessionId, rule));
    } catch {
      toast.error(t('chat.perm.session_rules.revoke_failed'));
    } finally {
      setSessionRulesBusy(false);
    }
  };

  // R106 清空本会话已记住决定：先 confirmDialog 确认，取消即不发请求。
  const clearSessionRules = async () => {
    if (!sessionId || sessionRulesBusy) return;
    const ok = await confirmDialog({
      title: t('chat.perm.session_rules.clear_confirm_title'),
      message: t('chat.perm.session_rules.clear_confirm_message'),
      confirmLabel: t('chat.perm.session_rules.clear_all'),
      danger: true,
    });
    if (!ok) return;
    setSessionRulesBusy(true);
    try {
      setSessionRules(await permissionApi.clearSessionRememberedRules(sessionId));
    } catch {
      toast.error(t('chat.perm.session_rules.revoke_failed'));
    } finally {
      setSessionRulesBusy(false);
    }
  };

  const Icon = PRESET_ICON[preset];

  /* v8 ignore start */

  /* v8 ignore stop */

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
        {custom && <span className="text-ui-xs text-text-secondary">({t('chat.perm.custom')})</span>}
        <ChevronDown className="w-3 h-3 opacity-60" aria-hidden />
      </button>

      {sessionId && (count > 0 || sessionRules.length > 0) && (
        <button
          type="button"
          onClick={() => {
            setAuditOpen((v) => !v);
            setMenuOpen(false);
          }}
          title={t('chat.perm.audit_title')}
          data-testid="auto-approval-badge"
          className="flex items-center gap-1 px-1.5 py-1 text-ui-2xs rounded-radius-sm border border-border text-text-secondary hover:bg-bg-hover"
        >
          <ShieldCheck className="w-3 h-3 text-accent" aria-hidden />
          {count > 0
            ? t('chat.perm.auto_count').replace('{n}', String(count))
            : t('chat.perm.session_rules.badge').replace('{n}', String(sessionRules.length))}
        </button>
      )}

      {menuOpen && (
        <div
          role="menu"
          data-testid="permission-mode-menu"
          className={`absolute right-0 ${popupPos} z-30 w-64 rounded border border-border bg-surface shadow-lg p-1`}
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
                  <span className="block text-ui-2xs text-text-secondary">{t(`chat.perm.${p}.desc`)}</span>
                </span>
              </button>
            );
          })}
          <p className="px-2 pt-1 text-ui-xs text-text-secondary border-t border-border mt-1">
            {t('chat.perm.destructive_note')}
          </p>
        </div>
      )}

      {auditOpen && (
        <div
          data-testid="auto-approval-audit"
          className={`absolute right-0 ${popupPos} z-30 w-80 max-h-72 overflow-y-auto rounded border border-border bg-surface shadow-lg p-2`}
        >
          {(sessionRules.length > 0 || sessionRulesFailed) && (
            <div className="mb-2" data-testid="session-rules-section">
              <div className="flex items-center gap-2 mb-1">
                <p className="text-xs font-semibold text-text flex-1">
                  {t('chat.perm.session_rules.title')}
                </p>
                {sessionRules.length > 0 && (
                  <button
                    type="button"
                    data-testid="session-rules-clear"
                    disabled={sessionRulesBusy}
                    onClick={() => void clearSessionRules()}
                    className="px-1.5 py-0.5 text-ui-2xs border border-border rounded-radius-sm text-text hover:bg-bg-hover disabled:opacity-50"
                  >
                    {t('chat.perm.session_rules.clear_all')}
                  </button>
                )}
              </div>
              {sessionRulesFailed ? (
                <p className="text-xs text-error" data-testid="session-rules-load-failed">
                  {t('chat.perm.session_rules.load_failed')}
                </p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {sessionRules.map((rule, index) => (
                    <li
                      key={`${index}-${rule.tool_pattern}-${rule.decision}`}
                      className="flex items-center gap-2 text-xs"
                      data-testid="session-rule-item"
                    >
                      <code className="flex-1 break-all font-mono text-text">
                        {rule.tool_pattern}
                      </code>
                      <span className="text-text-secondary shrink-0">
                        {t(
                          `settings.permission.rules.decision.${rule.decision}` as TranslationKey,
                        )}
                      </span>
                      {(rule.plugin_status === 'uninstalled' ||
                        rule.plugin_status === 'missing') && (
                        <span className="px-1 rounded bg-bg-hover text-ui-xs text-text-secondary shrink-0">
                          {t(
                            rule.plugin_status === 'uninstalled'
                              ? 'settings.permission.rules.plugin_uninstalled'
                              : 'settings.permission.rules.plugin_missing',
                          )}
                        </span>
                      )}
                      {shadowedSessionRules.has(index) && (
                        <span
                          className="px-1 rounded bg-bg-hover text-ui-xs text-warning shrink-0"
                          data-testid={`session-rule-shadowed-${index}`}
                          title={t('settings.permission.rules.shadowed_title').replace(
                            '{pattern}',
                            shadowedSessionRules.get(index) ?? '',
                          )}
                        >
                          {t('settings.permission.rules.shadowed')}
                        </span>
                      )}
                      <button
                        type="button"
                        data-testid={`session-rule-revoke-${index}`}
                        aria-label={`${t('chat.perm.session_rules.revoke')} ${rule.tool_pattern}`}
                        disabled={sessionRulesBusy}
                        onClick={() => void revokeSessionRule(rule)}
                        className="px-1.5 py-0.5 text-ui-2xs border border-border rounded-radius-sm text-text hover:bg-bg-hover disabled:opacity-50 shrink-0"
                      >
                        {t('chat.perm.session_rules.revoke')}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <p className="text-xs font-semibold text-text mb-1">{t('chat.perm.audit_title')}</p>
          {items.length === 0 ? (
            <p className="text-xs text-text-secondary">{t('chat.perm.audit_empty')}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border">
              {items.map((it) => (
                <li key={it.seq} className="py-1.5 text-xs" data-testid="auto-approval-item">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-text">{it.tool_name}</span>
                    <span className="px-1 rounded bg-bg-hover text-ui-xs text-text-secondary">{it.capability}</span>
                    {auditPluginOwners.get(it.seq) ? (
                      <span
                        className="text-ui-xs text-text-secondary shrink-0"
                        data-testid={`auto-approval-plugin-${it.seq}`}
                      >
                        {t('permission.from_plugin')}: {auditPluginOwners.get(it.seq)}
                      </span>
                    ) : null}
                    <span className="ml-auto text-ui-xs text-text-secondary">{formatTime(it.created_at)}</span>
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
