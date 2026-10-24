/**
 * R97 已记住权限规则管理：列出经审批「记住我的选择」保存且当前
 * 生效的规则，并支持逐条删除（撤销持久信任）。
 *
 * 列表与删除都走 permissionApi → 后端 /permissions/rules 端点；
 * 后端以 parse_rules() 口径返回生效规则，删除按规则内容定位
 * （R99，期间新记规则也不会删错行），删除后返回最新列表，
 * 前端直接采用，不自行 splice 假定成功。失败时保留原列表并
 * 显示失败文案。规则新增仍只能由审批记住生成，这里没有写入口。
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
            disabled={deletingIndex !== null || clearing}
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
              <button
                type="button"
                data-testid={`permission-rule-delete-${index}`}
                aria-label={`${t('settings.permission.rules.delete')} ${rule.tool_pattern}`}
                disabled={deletingIndex !== null || clearing}
                onClick={() => void handleDelete(rule, index)}
                className="px-2 py-0.5 text-xs border border-border rounded-radius-sm bg-bg text-text hover:border-primary disabled:opacity-50"
              >
                {t('settings.permission.rules.delete')}
              </button>
            </li>
          ))}
        </ul>
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
    </div>
  );
}
