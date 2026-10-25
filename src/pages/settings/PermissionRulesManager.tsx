/**
 * R97 已记住权限规则管理：列出经审批「记住我的选择」保存且当前
 * 生效的规则，并支持逐条删除（撤销持久信任）。
 *
 * 列表与删除都走 permissionApi → 后端 /permissions/rules 端点；
 * 后端以 parse_rules() 口径返回生效规则，删除按规则内容定位
 * （R99，期间新记规则也不会删错行），删除后返回最新列表，
 * 前端直接采用，不自行 splice 假定成功。失败时保留原列表并
 * 显示失败文案。规则新增仍只能由审批记住生成，这里没有写入口。
 *
 * R101 起后端为每条规则附带插件归属只读标注；属于已卸载或
 * 无生命周期记录插件的「孤儿规则」在行内以徽标提示，方便
 * 用户辨认后自行决定删留。R102 起可按归属整组撤销：列表
 * 后按插件名汇总出删除操作（confirmDialog 确认后调用后
 * 端 delete-by-plugin，选择子只有插件名）。
 *
 * R104 起 missing 一类（无生命周期记录、无名字可做选择
 * 子）可一键整组清理：列表后出汇总行，confirmDialog 确
 * 认后调用 delete-orphans；删除集合由后端同口径选出，
 * 前端只负责计数显示。
 */
import { useEffect, useState } from 'react';

import { permissionApi, type PermissionRuleItem } from '../../shared/api/permissionApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

export function PermissionRulesManager() {
  const { t } = useI18n();
  const [rules, setRules] = useState<PermissionRuleItem[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);
  const [clearFailed, setClearFailed] = useState(false);
  const [deletingIndex, setDeletingIndex] = useState<number | null>(null);
  const [clearing, setClearing] = useState(false);
  const [deletingPlugin, setDeletingPlugin] = useState<string | null>(null);
  const [pluginDeleteFailed, setPluginDeleteFailed] = useState(false);
  const [deletingOrphans, setDeletingOrphans] = useState(false);
  const [orphanDeleteFailed, setOrphanDeleteFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    permissionApi
      .listRules()
      .then((items) => {
        if (!cancelled) setRules(items);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleDelete = async (rule: PermissionRuleItem, index: number): Promise<void> => {
    setDeleteFailed(false);
    setDeletingIndex(index);
    try {
      const next = await permissionApi.deleteRule(rule);
      setRules(next);
    } catch {
      setDeleteFailed(true);
    } finally {
      setDeletingIndex(null);
    }
  };

  // R100 一键清空：破坏性操作（撤销全部持久信任）先走项目内
  // confirmDialog 确认，取消即无事发生、不发请求。
  const handleClear = async (): Promise<void> => {
    const ok = await confirmDialog({
      title: t('settings.permission.rules.clear_confirm_title'),
      message: t('settings.permission.rules.clear_confirm_message'),
      confirmLabel: t('settings.permission.rules.clear_all'),
      danger: true,
    });
    if (!ok) return;
    setClearFailed(false);
    setClearing(true);
    try {
      const next = await permissionApi.clearRules();
      setRules(next);
    } catch {
      setClearFailed(true);
    } finally {
      setClearing(false);
    }
  };

  // R102 按归属汇总：plugin_name 来自后端 R101 标注，这里
  // 只数每个插件名下有几条；无归属（内置工具/missing）不出现。
  const ownerCounts = new Map<string, number>();
  for (const rule of rules) {
    if (!rule.plugin_name) continue;
    ownerCounts.set(rule.plugin_name, (ownerCounts.get(rule.plugin_name) ?? 0) + 1);
  }
  const pluginOwners = [...ownerCounts.entries()];
  // R104 孤儿计数同样只读标注：plugin_status=missing 的条数。
  const orphanCount = rules.filter((rule) => rule.plugin_status === 'missing').length;
  const busy =
    deletingIndex !== null || clearing || deletingPlugin !== null || deletingOrphans;

  const handleDeleteByPlugin = async (pluginName: string): Promise<void> => {
    const ok = await confirmDialog({
      title: t('settings.permission.rules.delete_plugin_confirm_title'),
      message: pluginName,
      confirmLabel: t('settings.permission.rules.delete'),
      danger: true,
    });
    if (!ok) return;
    setPluginDeleteFailed(false);
    setDeletingPlugin(pluginName);
    try {
      const next = await permissionApi.deleteRulesByPlugin(pluginName);
      setRules(next);
    } catch {
      setPluginDeleteFailed(true);
    } finally {
      setDeletingPlugin(null);
    }
  };

  const handleDeleteOrphans = async (): Promise<void> => {
    const ok = await confirmDialog({
      title: t('settings.permission.rules.delete_orphans_confirm_title'),
      message: t('settings.permission.rules.delete_orphans_confirm_message'),
      confirmLabel: t('settings.permission.rules.delete'),
      danger: true,
    });
    if (!ok) return;
    setOrphanDeleteFailed(false);
    setDeletingOrphans(true);
    try {
      const next = await permissionApi.deleteOrphanRules();
      setRules(next);
    } catch {
      setOrphanDeleteFailed(true);
    } finally {
      setDeletingOrphans(false);
    }
  };

  return (
    <div className="mt-3" data-testid="permission-rules-manager">
      <div className="flex items-center gap-2">
        <p className="text-xs font-medium text-text flex-1">
          {t('settings.permission.rules.title')}
        </p>
        {rules.length > 0 && !loadFailed && (
          <button
            type="button"
            data-testid="permission-rules-clear"
            disabled={busy}
            onClick={() => void handleClear()}
            className="px-2 py-0.5 text-xs border border-border rounded-radius-sm bg-bg text-text hover:border-primary disabled:opacity-50"
          >
            {t('settings.permission.rules.clear_all')}
          </button>
        )}
      </div>
      {loadFailed ? (
        <p className="text-xs text-error mt-1" data-testid="permission-rules-load-failed">
          {t('settings.permission.rules.load_failed')}
        </p>
      ) : rules.length === 0 ? (
        <p className="text-xs text-muted mt-1">{t('settings.permission.rules.empty')}</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {rules.map((rule, index) => (
            <li
              key={`${index}-${rule.tool_pattern}-${rule.decision}`}
              className="flex items-center gap-2 text-xs"
            >
              <code className="flex-1 break-all">{rule.tool_pattern}</code>
              <span className="text-muted">
                {t(`settings.permission.rules.decision.${rule.decision}` as TranslationKey)}
              </span>
              {(rule.plugin_status === 'uninstalled' || rule.plugin_status === 'missing') && (
                <span
                  className="px-1 border border-border rounded-radius-sm text-muted shrink-0"
                  data-testid={`permission-rule-plugin-status-${index}`}
                >
                  {t(
                    rule.plugin_status === 'uninstalled'
                      ? 'settings.permission.rules.plugin_uninstalled'
                      : 'settings.permission.rules.plugin_missing',
                  )}
                </span>
              )}
              <button
                type="button"
                data-testid={`permission-rule-delete-${index}`}
                aria-label={`${t('settings.permission.rules.delete')} ${rule.tool_pattern}`}
                disabled={busy}
                onClick={() => void handleDelete(rule, index)}
                className="px-2 py-0.5 text-xs border border-border rounded-radius-sm bg-bg text-text hover:border-primary disabled:opacity-50"
              >
                {t('settings.permission.rules.delete')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {!loadFailed && pluginOwners.length > 0 && (
        <ul className="mt-1 space-y-1">
          {pluginOwners.map(([name, count]) => (
            <li key={name} className="flex items-center gap-2 text-xs">
              <span className="flex-1 text-muted">
                {`${t('settings.permission.rules.by_plugin')} `}
                <code className="break-all">{name}</code>
                {` · ${count}`}
              </span>
              <button
                type="button"
                data-testid={`permission-rules-delete-by-plugin-${name}`}
                disabled={busy}
                onClick={() => void handleDeleteByPlugin(name)}
                className="px-2 py-0.5 text-xs border border-border rounded-radius-sm bg-bg text-text hover:border-primary disabled:opacity-50"
              >
                {t('settings.permission.rules.delete')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {!loadFailed && orphanCount > 0 && (
        <div className="mt-1 flex items-center gap-2 text-xs">
          <span className="flex-1 text-muted">
            {`${t('settings.permission.rules.orphans')} · ${orphanCount}`}
          </span>
          <button
            type="button"
            data-testid="permission-rules-delete-orphans"
            disabled={busy}
            onClick={() => void handleDeleteOrphans()}
            className="px-2 py-0.5 text-xs border border-border rounded-radius-sm bg-bg text-text hover:border-primary disabled:opacity-50"
          >
            {t('settings.permission.rules.delete')}
          </button>
        </div>
      )}
      {deleteFailed && (
        <p className="text-xs text-error mt-1" data-testid="permission-rules-delete-failed">
          {t('settings.permission.rules.delete_failed')}
        </p>
      )}
      {clearFailed && (
        <p className="text-xs text-error mt-1" data-testid="permission-rules-clear-failed">
          {t('settings.permission.rules.clear_failed')}
        </p>
      )}
      {pluginDeleteFailed && (
        <p
          className="text-xs text-error mt-1"
          data-testid="permission-rules-delete-by-plugin-failed"
        >
          {t('settings.permission.rules.delete_plugin_failed')}
        </p>
      )}
      {orphanDeleteFailed && (
        <p
          className="text-xs text-error mt-1"
          data-testid="permission-rules-delete-orphans-failed"
        >
          {t('settings.permission.rules.delete_orphans_failed')}
        </p>
      )}
    </div>
  );
}
