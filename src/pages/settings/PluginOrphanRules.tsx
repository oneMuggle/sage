/**
 * R103 已卸载插件的孤儿规则提示与就地清理。
 *
 * 卸载是可恢复的软删除，不会联动删除其已记住规则（R101
 * 结论）。本组件在孤儿产生地——插件卡片上——提示「这个
 * 已卸载插件名下还剩几条规则」，删除永远是用户显式点击
 * + confirmDialog 确认，实际删除走 R102 的
 * deleteRulesByPlugin（服务端按归属选集）。计数由父组件
 * 用 R101 标注汇总后传入，本组件只负责单卡交互。
 */
import { useState } from 'react';

import { permissionApi } from '../../shared/api/permissionApi';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

interface PluginOrphanRulesProps {
  pluginName: string;
  count: number;
  en: boolean;
  disabled: boolean;
  onDeleted: (notice: string) => void;
  onError: (message: string) => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function PluginOrphanRules({
  pluginName,
  count,
  en,
  disabled,
  onDeleted,
  onError,
}: PluginOrphanRulesProps) {
  const [busy, setBusy] = useState(false);
  const orphanRules = en ? 'Remembered permission rules remain' : '卸载后仍保留的已记住规则';
  const deleteLabel = en ? 'Delete its rules' : '删除其全部规则';

  const handleDelete = async (): Promise<void> => {
    const ok = await confirmDialog({
      title: en
        ? 'Delete all remembered rules for this plugin?'
        : '删除该插件的全部已记住规则？',
      message: pluginName,
      confirmLabel: deleteLabel,
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await permissionApi.deleteRulesByPlugin(pluginName);
      onDeleted(
        en
          ? 'Remembered rules for this plugin were deleted.'
          : '该插件的已记住规则已删除。',
      );
    } catch (error) {
      onError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="mt-2 flex flex-wrap items-center gap-2 text-xs"
      data-testid={`plugin-orphan-rules-${pluginName}`}
    >
      <span className="text-error">{`${orphanRules} · ${count}`}</span>
      <button
        type="button"
        data-testid={`plugin-delete-rules-${pluginName}`}
        className="rounded-radius-sm border border-error/40 px-2 py-0.5 text-xs text-error hover:bg-error/10 disabled:opacity-50"
        disabled={disabled || busy}
        onClick={() => void handleDelete()}
      >
        {deleteLabel}
      </button>
    </div>
  );
}
