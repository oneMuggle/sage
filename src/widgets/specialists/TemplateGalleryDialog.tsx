import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  specialistApi,
  type InstantiateTemplateResult,
  type SpecialistTemplateMeta,
} from '../../shared/api/specialistApi';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';

interface TemplateGalleryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 实例化成功后回调；父组件通常用来刷新专家列表。 */
  onCreated: (result: InstantiateTemplateResult) => void;
}

/**
 * 内置模板画廊对话框（M4-T2，spec §9）。
 *
 * 以网格展示写作/研究/编码/演示/Office 5 套内置模板，每张卡片展示
 * 头像 + 名称 + 标语 + 描述 + 技能数；点击「创建」调用后端实例化端点。
 */
export function TemplateGalleryDialog({
  open,
  onOpenChange,
  onCreated,
}: TemplateGalleryDialogProps) {
  const [templates, setTemplates] = useState<SpecialistTemplateMeta[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [creatingId, setCreatingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setLoadingError(null);
    specialistApi
      .listTemplates()
      .then((list) => {
        if (!cancelled) setTemplates(list);
      })
      .catch((err) => {
        if (!cancelled) setLoadingError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleCreate = useCallback(
    async (tpl: SpecialistTemplateMeta) => {
      setCreatingId(tpl.id);
      try {
        const result = await specialistApi.instantiateTemplate(tpl.id);
        toast.success(`已创建专家「${result.name}」`);
        onCreated(result);
        onOpenChange(false);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        toast.error(`创建失败：${message}`);
      } finally {
        setCreatingId(null);
      }
    },
    [onCreated, onOpenChange],
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>从模板创建专家</DialogTitle>
          <DialogDescription>
            选择一套内置模板一键创建专家；创建后仍可在「编辑」中自由定制人设与技能。
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4">
          {loading ? (
            <div className="rounded-lg border border-border bg-bg-subtle/40 p-6 text-center text-sm text-muted">
              加载模板…
            </div>
          ) : loadingError ? (
            <div className="rounded-lg border border-border border-error/30 bg-bg-subtle/40 p-6 text-center text-sm text-error">
              加载模板失败：{loadingError}
            </div>
          ) : templates.length === 0 ? (
            <div className="rounded-lg border border-border bg-bg-subtle/40 p-6 text-center text-sm text-muted">
              暂无可用模板。
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {templates.map((tpl) => (
                <div
                  key={tpl.id}
                  className="flex flex-col gap-2 rounded-lg border border-border bg-surface-elevated/60 p-4"
                >
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-full bg-bg-subtle text-xl">
                      {tpl.avatar}
                    </span>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{tpl.name}</div>
                      {tpl.tagline && (
                        <div className="truncate text-xs text-muted">{tpl.tagline}</div>
                      )}
                    </div>
                  </div>
                  {tpl.description && (
                    <p className="line-clamp-2 text-xs text-muted">{tpl.description}</p>
                  )}
                  <div className="mt-auto flex items-center justify-between pt-2">
                    <span className="text-xs text-muted">
                      {tpl.skill_count > 0 ? `${tpl.skill_count} 项技能` : '无技能'}
                    </span>
                    <Button
                      size="sm"
                      disabled={creatingId === tpl.id}
                      onClick={() => handleCreate(tpl)}
                    >
                      {creatingId === tpl.id ? '创建中…' : '创建'}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
