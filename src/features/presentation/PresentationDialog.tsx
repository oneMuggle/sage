/**
 * PresentationDialog — 把一组 SVG 幻灯片交给后端确定性工程层，
 * 转成原生可编辑 PPTX，并展示质量门禁结果。
 *
 * Phase 1 不在这里做 AI 创作：SVG 由对话/智能体产出后，用户以文件或
 * 粘贴方式导入本对话框。后端契约见 backend/api/presentation_routes.py：
 * POST /api/v1/presentation/render-svgs。
 */

import { FileImage, Plus, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { presentationApi } from '../../shared/api/presentationApi';
import type {
  PresentationEnvironment,
  PresentationRenderResult,
  PresentationTemplate,
  PresentationTemplateKind,
} from '../../shared/api/presentationApi';
import { Button } from '../../shared/ui/Button';
import { Modal } from '../../shared/ui/Modal';
import { useTaskCenterStore } from '../task-center/taskCenterStore';

import { QualityReport } from './QualityReport';

const TASK_ID = 'presentation:render';
const DEFAULT_FILENAME = 'presentation.pptx';

const inputClass = 'w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text';

/** 模板选择器分组顺序与中文名。 */
const TEMPLATE_GROUPS: Array<{ kind: PresentationTemplateKind; label: string }> = [
  { kind: 'brand', label: '品牌' },
  { kind: 'style', label: '风格' },
  { kind: 'layout', label: '版式' },
  { kind: 'deck', label: '整套' },
];

/** 依赖页面结构解析的模板种类：缺少结构元数据时按扁平方式导出。 */
const STRUCTURAL_TEMPLATE_KINDS: ReadonlySet<string> = new Set(['layout', 'deck']);
const STRUCTURE_MARKER = 'data-pptx-layout';

interface SlideEntry {
  id: string;
  name: string;
  content: string;
  size: number;
}

export interface PresentationDialogProps {
  isOpen: boolean;
  onClose: () => void;
  workspacePath: string;
}

function ensurePptxSuffix(filename: string): string {
  const trimmed = filename.trim();
  if (!trimmed) return DEFAULT_FILENAME;
  return trimmed.toLowerCase().endsWith('.pptx') ? trimmed : `${trimmed}.pptx`;
}

function looksLikeSvg(text: string): boolean {
  return /<svg[\s>]/i.test(text);
}

function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `slide-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function PresentationDialog({ isOpen, onClose, workspacePath }: PresentationDialogProps) {
  const [slides, setSlides] = useState<SlideEntry[]>([]);
  const [filename, setFilename] = useState(DEFAULT_FILENAME);
  const [pasteText, setPasteText] = useState('');
  const [env, setEnv] = useState<PresentationEnvironment | null>(null);
  const [envError, setEnvError] = useState<string | null>(null);
  const [envLoading, setEnvLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PresentationRenderResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [templates, setTemplates] = useState<PresentationTemplate[]>([]);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templatesRefreshing, setTemplatesRefreshing] = useState(false);
  const [selected, setSelected] = useState<Partial<Record<PresentationTemplateKind, string>>>({});

  const registerTask = useTaskCenterStore((s) => s.registerTask);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 每次打开都重新自检环境（技能目录/解释器可能被移动或卸载），
  // 同时清空上一轮的产物与错误，避免残留状态误导用户。
  useEffect(() => {
    if (!isOpen) return;
    setResult(null);
    setError(null);
    setSelected({});
    setEnvLoading(true);
    setEnvError(null);
    presentationApi
      .getEnvironment()
      .then(setEnv)
      .catch((e: unknown) => {
        setEnv(null);
        setEnvError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => setEnvLoading(false));

    setTemplatesLoading(true);
    setTemplateError(null);
    presentationApi
      .getTemplates()
      .then((list) => {
        setTemplates(list.templates);
        setTemplateError(list.error ?? null);
      })
      .catch((e: unknown) => {
        setTemplates([]);
        setTemplateError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => setTemplatesLoading(false));
  }, [isOpen]);

  const handleRefreshTemplates = async () => {
    setTemplatesRefreshing(true);
    try {
      const res = await presentationApi.refreshTemplates();
      if (res.available) {
        toast.success(`模板库已刷新：${res.count} 个模板`);
        const list = await presentationApi.getTemplates();
        setTemplates(list.templates);
        setTemplateError(list.error ?? null);
      } else {
        setTemplateError(res.error ?? '模板库不可用');
      }
    } catch (e) {
      setTemplateError(e instanceof Error ? e.message : String(e));
    } finally {
      setTemplatesRefreshing(false);
    }
  };

  const addSlide = (name: string, content: string, size: number) => {
    setSlides((prev) => [...prev, { id: randomId(), name, content, size }]);
  };

  const handleFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    const incoming = Array.from(fileList);
    for (const file of incoming) {
      if (!file.name.toLowerCase().endsWith('.svg')) {
        toast.error(`仅支持 .svg 文件：${file.name}`);
        continue;
      }
      try {
        const text = await file.text();
        if (!looksLikeSvg(text)) {
          toast.error(`不是有效的 SVG 内容：${file.name}`);
          continue;
        }
        addSlide(file.name, text, file.size);
      } catch (e) {
        toast.error(`读取失败：${file.name}（${e instanceof Error ? e.message : String(e)}）`);
      }
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleAddPaste = () => {
    const text = pasteText.trim();
    if (!text) return;
    if (!looksLikeSvg(text)) {
      toast.error('粘贴内容不是有效的 SVG（缺少 <svg> 标签）');
      return;
    }
    addSlide(`粘贴的幻灯片 ${slides.length + 1}`, text, new Blob([text]).size);
    setPasteText('');
  };

  const removeSlide = (id: string) => {
    setSlides((prev) => prev.filter((s) => s.id !== id));
  };

  const moveSlide = (index: number, delta: number) => {
    setSlides((prev) => {
      const target = index + delta;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      const [item] = next.splice(index, 1);
      next.splice(target, 0, item);
      return next;
    });
  };

  const canSubmit = !busy && Boolean(workspacePath) && slides.length > 0 && env?.ready === true;

  const templateGroups = TEMPLATE_GROUPS.map((group) => ({
    ...group,
    items: templates.filter((t) => t.kind === group.kind),
  })).filter((group) => group.items.length > 0);

  const selectedTemplateIds = TEMPLATE_GROUPS.map((group) => selected[group.kind]).filter(
    (value): value is string => Boolean(value),
  );

  const structuralHint =
    slides.length > 0 &&
    selectedTemplateIds.some((id) => STRUCTURAL_TEMPLATE_KINDS.has(id.split(':')[0])) &&
    !slides.some((slide) => slide.content.includes(STRUCTURE_MARKER))
      ? '所选的版式/整套模板依赖页面的结构化元数据（data-pptx-layout），当前 SVG 未检测到，导出可能不应用其版式。'
      : null;

  const handleRender = async () => {
    if (!canSubmit) return;
    const outputName = ensurePptxSuffix(filename);
    setBusy(true);
    setResult(null);
    setError(null);
    registerTask(TASK_ID, 'office', '正在渲染演示文稿', '质量检查与转换');
    try {
      const res = await presentationApi.renderFromSvgs({
        workspace_path: workspacePath,
        filename: outputName,
        svg_slides: slides.map((s) => s.content),
        ...(selectedTemplateIds.length > 0 ? { template_ids: selectedTemplateIds } : {}),
      });
      setResult(res);
      if (res.success) {
        useTaskCenterStore.getState().completeTask(TASK_ID, 'succeeded');
        toast.success(`演示文稿已生成：${res.output_path ?? outputName}`);
      } else {
        useTaskCenterStore
          .getState()
          .completeTask(TASK_ID, 'failed', res.message || '质量门禁未通过');
        toast.error(res.message || '质量门禁未通过，未产出文件');
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      useTaskCenterStore.getState().completeTask(TASK_ID, 'failed', msg);
      toast.error(`渲染失败：${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const handleClose = () => {
    if (busy) return;
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="SVG → 可编辑 PPT"
      size="xl"
      footer={
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-muted">
            {slides.length > 0 ? `已添加 ${slides.length} 页` : '尚未添加幻灯片'}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={handleClose} disabled={busy}>
              取消
            </Button>
            <Button onClick={handleRender} disabled={!canSubmit}>
              {busy ? '渲染中…' : '生成 PPTX'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-4">
        {/* 环境自检 */}
        {envLoading ? (
          <p className="text-xs text-muted" data-testid="presentation-env-loading">
            正在检查 ppt-master 环境…
          </p>
        ) : envError ? (
          <div
            className="rounded border border-error/30 bg-error/10 px-3 py-2 text-xs text-error"
            data-testid="presentation-env-error"
          >
            环境自检失败：{envError}
          </div>
        ) : env && !env.ready ? (
          <div
            className="rounded border border-error/30 bg-error/10 px-3 py-2 text-xs text-error"
            data-testid="presentation-env-not-ready"
          >
            ppt-master 环境不可用{env.error ? `：${env.error}` : ''}
          </div>
        ) : null}

        {!workspacePath ? (
          <div
            className="rounded border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning"
            data-testid="presentation-no-workspace"
          >
            请先绑定工作区后再生成演示文稿。
          </div>
        ) : null}

        {/* 文件名 */}
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1">输出文件名</label>
          <input
            className={inputClass}
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder={DEFAULT_FILENAME}
            disabled={busy}
            data-testid="presentation-filename"
          />
        </div>

        {/* 模板库（可选） */}
        {templateGroups.length > 0 ? (
          <div className="space-y-2" data-testid="presentation-templates">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium text-text-secondary">
                模板库（可选，每类最多一个）
              </label>
              <button
                type="button"
                className="text-xs text-muted hover:text-text disabled:opacity-40"
                onClick={() => void handleRefreshTemplates()}
                disabled={busy || templatesRefreshing}
                data-testid="presentation-templates-refresh"
              >
                {templatesRefreshing ? '刷新中…' : '刷新模板库'}
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {templateGroups.map((group) => (
                <label key={group.kind} className="block text-xs text-text-secondary">
                  {group.label}
                  <select
                    className={`${inputClass} mt-1`}
                    value={selected[group.kind] ?? ''}
                    onChange={(e) =>
                      setSelected((prev) => ({
                        ...prev,
                        [group.kind]: e.target.value || undefined,
                      }))
                    }
                    disabled={busy}
                    data-testid={`presentation-template-${group.kind}`}
                  >
                    <option value="">不使用</option>
                    {group.items.map((item) => (
                      <option
                        key={item.template_id}
                        value={`${item.kind}:${item.template_id}`}
                        title={item.summary}
                      >
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            {structuralHint ? (
              <p className="text-xs text-warning" data-testid="presentation-template-hint">
                {structuralHint}
              </p>
            ) : null}
          </div>
        ) : templatesLoading ? (
          <p className="text-xs text-muted" data-testid="presentation-templates-loading">
            正在加载模板库…
          </p>
        ) : templateError ? (
          <p className="text-xs text-muted" data-testid="presentation-templates-error">
            模板库不可用：{templateError}
          </p>
        ) : null}

        {/* 导入 SVG */}
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".svg,image/svg+xml"
            multiple
            className="hidden"
            onChange={(e) => void handleFiles(e.target.files)}
            data-testid="presentation-file-input"
          />
          <Button variant="secondary" onClick={() => fileInputRef.current?.click()} disabled={busy}>
            <Plus className="w-4 h-4 mr-1" />
            添加 SVG 文件
          </Button>
          <span className="text-xs text-muted">支持多选；文件按添加顺序作为幻灯片页序。</span>
        </div>

        {/* 粘贴 SVG */}
        <details className="rounded border border-border bg-bg-subtle">
          <summary className="cursor-pointer select-none px-3 py-2 text-sm text-text">
            或粘贴 SVG 源码
          </summary>
          <div className="border-t border-border p-3 space-y-2">
            <textarea
              className={`${inputClass} font-mono h-28 resize-y`}
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              placeholder="<svg xmlns=…>…</svg>"
              disabled={busy}
              data-testid="presentation-paste"
            />
            <Button
              variant="secondary"
              onClick={handleAddPaste}
              disabled={busy || !pasteText.trim()}
            >
              添加为幻灯片
            </Button>
          </div>
        </details>

        {/* 幻灯片列表 */}
        {slides.length > 0 ? (
          <ul className="space-y-1" data-testid="presentation-slide-list">
            {slides.map((slide, index) => (
              <li
                key={slide.id}
                className="flex items-center gap-2 rounded border border-border bg-surface px-3 py-1.5 text-sm"
                data-testid="presentation-slide-item"
              >
                <FileImage className="w-4 h-4 text-muted shrink-0" />
                <span className="w-6 text-xs text-muted shrink-0">{index + 1}</span>
                <span className="flex-1 truncate" title={slide.name}>
                  {slide.name}
                </span>
                <span className="text-xs text-muted shrink-0">{formatSize(slide.size)}</span>
                <button
                  className="p-1 text-muted hover:text-text disabled:opacity-40"
                  onClick={() => moveSlide(index, -1)}
                  disabled={busy || index === 0}
                  aria-label="上移"
                  type="button"
                >
                  ↑
                </button>
                <button
                  className="p-1 text-muted hover:text-text disabled:opacity-40"
                  onClick={() => moveSlide(index, 1)}
                  disabled={busy || index === slides.length - 1}
                  aria-label="下移"
                  type="button"
                >
                  ↓
                </button>
                <button
                  className="p-1 text-muted hover:text-error disabled:opacity-40"
                  onClick={() => removeSlide(slide.id)}
                  disabled={busy}
                  aria-label="移除"
                  type="button"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted">还没有幻灯片，请添加 SVG 文件或粘贴源码。</p>
        )}

        {/* 错误 */}
        {error ? (
          <div
            className="rounded border border-error/30 bg-error/10 px-3 py-2 text-xs text-error"
            data-testid="presentation-error"
          >
            {error}
          </div>
        ) : null}

        {/* 质量报告 */}
        {result ? (
          <QualityReport
            success={result.success}
            qualityPassed={result.quality_passed}
            blockingErrors={result.blocking_errors}
            warnings={result.warnings}
            summary={result.summary}
            message={result.message}
            outputPath={result.output_path}
            templatesApplied={result.templates_applied}
          />
        ) : null}
      </div>
    </Modal>
  );
}
