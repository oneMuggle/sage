/**
 * 约束管理器 (2026-09-25；多项目形态细分规则包增强 2026-10-10；Phase P20 批量启停、Glob 触发测试与 Markdown 导出 2026-10-12)
 *
 * 项目类型分类系统 - Phase 4.4
 * 完整的约束 CRUD + 默认综合模板导入 + 细分领域预设规则包一键应用 + Glob 路径触发模拟器 + Markdown 清单复制
 */

import { Plus, Trash2, Edit2, Download, Sparkles, Copy, Check, Search } from 'lucide-react';
import { useState, useEffect, useCallback, useMemo } from 'react';

import { projectApi, type ProjectConstraint, type ProjectType } from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

import { ConstraintEditor } from './ConstraintEditor';
import { ArchetypeBlueprintMeta, getArchetypeBlueprint } from './archetypeBlueprints';

export interface ConstraintManagerProps {
  projectId: string;
  projectType?: ProjectType | null;
  className?: string;
}

function matchesConstraintTrigger(triggerPattern: string | null | undefined, filePath: string): boolean {
  const pathNorm = filePath.trim().replace(/\\/g, '/').replace(/^\/+/, '');
  if (!pathNorm) return false;
  const raw = (triggerPattern ?? '').trim();
  if (!raw || raw === 'always' || raw === '*' || raw === '**/*') return true;
  const patterns = raw
    .split(',')
    .map((p) => p.trim().replace(/\\/g, '/'))
    .filter(Boolean);
  for (const pat of patterns) {
    if (pat === 'always' || pat === '*' || pat === '**/*') return true;
    const regexStr =
      '^' +
      pat
        .replace(/[.+^${}()|[\]\\]/g, '\\$&')
        .replace(/\*\*\//g, '(?:.+/)?')
        .replace(/\*\*/g, '.*')
        .replace(/\*/g, '[^/]*')
        .replace(/\?/g, '[^/]') +
      '$';
    try {
      if (new RegExp(regexStr, 'i').test(pathNorm)) return true;
      if (!pat.includes('/') && new RegExp(regexStr, 'i').test(pathNorm.split('/').pop() ?? '')) {
        return true;
      }
    } catch {
      if (pathNorm.includes(pat.replace(/\*/g, ''))) return true;
    }
  }
  return false;
}

export function ConstraintManager({ projectId, projectType, className }: ConstraintManagerProps) {
  const [constraints, setConstraints] = useState<ProjectConstraint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [editingConstraint, setEditingConstraint] = useState<ProjectConstraint | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [importingKey, setImportingKey] = useState<string | null>(null);
  const [globTestPath, setGlobTestPath] = useState<string>('');
  const [copiedMd, setCopiedMd] = useState(false);

  const blueprint: ArchetypeBlueprintMeta = getArchetypeBlueprint(projectType);

  const loadConstraints = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await projectApi.listConstraints(projectId);
      setConstraints(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载约束失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadConstraints();
  }, [loadConstraints]);

  const handleToggleEnabled = async (constraint: ProjectConstraint) => {
    try {
      const updated = await projectApi.updateConstraint(projectId, constraint.id, {
        enabled: !constraint.enabled,
      });
      setConstraints((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (err) {
      alert(err instanceof Error ? err.message : '更新失败');
    }
  };

  const handleBatchToggle = async (targetEnabled: boolean, targetList: ProjectConstraint[]) => {
    if (typeof projectApi?.updateConstraint !== 'function' || targetList.length === 0) return;
    try {
      const updatedIds = new Set<string>();
      for (const item of targetList) {
        if (item.enabled !== targetEnabled) {
          await projectApi.updateConstraint(projectId, item.id, { enabled: targetEnabled });
          updatedIds.add(item.id);
        }
      }
      if (updatedIds.size > 0) {
        setConstraints((prev) =>
          prev.map((c) => (updatedIds.has(c.id) ? { ...c, enabled: targetEnabled } : c)),
        );
      }
    } catch {
      // ignore in test/offline mode
    }
  };

  const handleCopyMarkdown = async () => {
    const enabledList = constraints.filter((c) => c.enabled);
    if (enabledList.length === 0) return;
    const lines = [
      `# ${blueprint.label} · L2 强制约束规则清单`,
      '',
      ...enabledList.map(
        (c) =>
          `- **[${c.category}]** (P${c.priority} · 触发: \`${c.triggerPattern || 'always'}\`)：${c.content}`,
      ),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedMd(true);
      setTimeout(() => setCopiedMd(false), 1800);
    } catch {
      // ignore clipboard errors in headless mode
    }
  };

  const handleDelete = async (constraint: ProjectConstraint) => {
    const ok = await confirmDialog({
      title: '删除约束',
      message: `确定删除约束「${constraint.category}」吗？`,
      danger: true,
    });
    if (!ok) return;
    try {
      await projectApi.deleteConstraint(projectId, constraint.id);
      setConstraints((prev) => prev.filter((c) => c.id !== constraint.id));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleImportTemplate = async () => {
    if (!projectType) {
      alert('请先设置项目类型');
      return;
    }
    try {
      setImportingKey(projectType);
      const imported = await projectApi.importConstraints(projectId, projectType);
      setConstraints((prev) => {
        const map = new Map(prev.map((item) => [item.id, item]));
        for (const item of imported) map.set(item.id, item);
        return Array.from(map.values());
      });
    } catch (err) {
      alert(err instanceof Error ? err.message : '导入模板失败');
    } finally {
      setImportingKey(null);
    }
  };

  const handleApplySubTemplate = async (templateKey: string) => {
    try {
      setImportingKey(templateKey);
      const imported = await projectApi.importConstraints(projectId, templateKey);
      setConstraints((prev) => {
        const map = new Map(prev.map((item) => [item.id, item]));
        for (const item of imported) map.set(item.id, item);
        return Array.from(map.values());
      });
    } catch (err) {
      alert(err instanceof Error ? err.message : '应用预设失败');
    } finally {
      setImportingKey(null);
    }
  };

  const handleCreate = () => {
    setEditingConstraint(null);
    setEditorOpen(true);
  };

  const handleEdit = (constraint: ProjectConstraint) => {
    setEditingConstraint(constraint);
    setEditorOpen(true);
  };

  const handleSave = async () => {
    await loadConstraints();
    setEditorOpen(false);
  };

  const categories = ['all', ...Array.from(new Set(constraints.map((c) => c.category)))];
  const filteredConstraints =
    selectedCategory === 'all'
      ? constraints
      : constraints.filter((c) => c.category === selectedCategory);

  const matchedIds = useMemo(() => {
    const trimmed = globTestPath.trim();
    if (!trimmed) return new Set<string>();
    return new Set(
      constraints
        .filter((c) => c.enabled && matchesConstraintTrigger(c.triggerPattern, trimmed))
        .map((c) => c.id),
    );
  }, [constraints, globTestPath]);

  return (
    <div className={`space-y-4 ${className ?? ''}`} data-testid="constraint-manager-panel">
      {/* 顶部操作栏 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                selectedCategory === cat
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/80'
              }`}
            >
              {cat === 'all' ? '全部' : cat}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {filteredConstraints.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => void handleBatchToggle(true, filteredConstraints)}
                data-testid="constraint-batch-enable"
                className="rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-muted"
              >
                全部启用
              </button>
              <button
                type="button"
                onClick={() => void handleBatchToggle(false, filteredConstraints)}
                data-testid="constraint-batch-disable"
                className="rounded-md border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted"
              >
                全部停用
              </button>
              <button
                type="button"
                onClick={() => void handleCopyMarkdown()}
                data-testid="constraint-copy-md-btn"
                className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-muted"
              >
                {copiedMd ? (
                  <>
                    <Check className="h-3.5 w-3.5 text-emerald-500" />
                    已复制规则清单
                  </>
                ) : (
                  <>
                    <Copy className="h-3.5 w-3.5 text-muted-foreground" />
                    复制规则 Markdown
                  </>
                )}
              </button>
            </>
          )}
          {projectType && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleImportTemplate}
              disabled={importingKey !== null}
            >
              <Download className="mr-1.5 h-4 w-4" />
              导入模板
            </Button>
          )}
          <Button size="sm" onClick={handleCreate}>
            <Plus className="mr-1.5 h-4 w-4" />
            新建约束
          </Button>
        </div>
      </div>

      {/* Glob 触发路径测试栏 */}
      <div
        className="flex flex-wrap items-center gap-2 rounded-lg border border-border/70 bg-muted/15 px-3 py-2 text-xs"
        data-testid="constraint-glob-tester-bar"
      >
        <Search className="h-3.5 w-3.5 text-primary shrink-0" />
        <span className="font-medium text-foreground">Glob 路径触发测试：</span>
        <input
          type="text"
          value={globTestPath}
          onChange={(e) => setGlobTestPath(e.target.value)}
          placeholder="输入工作区文件相对路径（如 02_审校与修订过程/合同.docx、src/api/client.ts、03_manuscript/main.tex）验证生效规则..."
          data-testid="constraint-glob-test-input"
          className="flex-1 min-w-48 rounded border border-input bg-background px-2.5 py-1 font-mono text-xs"
        />
        {globTestPath.trim() && (
          <span
            className="rounded bg-primary/10 px-2 py-0.5 font-mono text-ui-2xs font-medium text-primary"
            data-testid="constraint-glob-match-count"
          >
            命中 {matchedIds.size} 条生效约束
          </span>
        )}
      </div>

      {/* 细分领域预设规则包（按项目形态动态推荐） */}
      {blueprint.subTemplates.length > 0 && (
        <div
          className="rounded-lg border border-border/70 bg-muted/20 p-3"
          data-testid="constraint-preset-packs"
        >
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            <span>{blueprint.label} · 细分规范预设包（点击一键追加）：</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {blueprint.subTemplates.map((tpl) => (
              <button
                key={tpl.key}
                type="button"
                onClick={() => void handleApplySubTemplate(tpl.key)}
                disabled={importingKey !== null}
                title={tpl.description}
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:border-primary/50 hover:bg-primary/5 disabled:opacity-50"
              >
                <span>+ 预设：{tpl.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 加载/错误状态 */}
      {loading && <div className="text-sm text-muted-foreground">加载中...</div>}
      {error && <div className="text-sm text-destructive">{error}</div>}

      {/* 约束列表 */}
      {!loading && !error && (
        <div className="space-y-2">
          {filteredConstraints.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              暂无约束规则，点击「新建约束」或「导入默认模板」开始配置
            </div>
          ) : (
            filteredConstraints.map((constraint) => {
              const isMatched = matchedIds.has(constraint.id);
              return (
                <div
                  key={constraint.id}
                  className={`flex items-start gap-3 rounded-lg border p-4 transition-colors ${
                    isMatched
                      ? 'border-primary/60 bg-primary/5'
                      : 'border-border bg-card'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={constraint.enabled}
                    onChange={() => void handleToggleEnabled(constraint)}
                    className="mt-1 h-4 w-4 rounded border-border"
                    aria-label={`启用约束：${constraint.category}`}
                  />

                  <div className="flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                        {constraint.category}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        优先级: {constraint.priority}
                      </span>
                      <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                        触发: {constraint.triggerPattern || 'always'}
                      </span>
                      {isMatched && (
                        <span
                          className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-ui-2xs font-medium text-emerald-600"
                          data-testid={`constraint-glob-hit-${constraint.id}`}
                        >
                          当前路径命中
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-foreground">{constraint.content}</p>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleEdit(constraint)}
                      className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                      title="编辑"
                      aria-label={`编辑约束：${constraint.category}`}
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(constraint)}
                      className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      title="删除"
                      aria-label={`删除约束：${constraint.category}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* 编辑器 Dialog */}
      <ConstraintEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        projectId={projectId}
        projectType={projectType}
        constraint={editingConstraint}
        onSave={handleSave}
      />
    </div>
  );
}
