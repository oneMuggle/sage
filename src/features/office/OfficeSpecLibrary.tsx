/**
 * OfficeSpecLibrary (M2.5) — 格式规范书库。
 *
 * 列出工作区所有规范书（默认排最前），支持：设为默认 / 清除默认 / 删除；
 * 从说明文件提取草稿规则包后保存为新规范书；引用已有规则包快速创建；
 * 把规范书绑定到单个文档（文档级优先于工作区默认）。
 *
 * 样式与交互沿用 WordRuleExtractionPanel（中文文案、data-testid、无全局状态）。
 */

import { useCallback, useEffect, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type { OfficeSpecDocument } from '../../shared/api/officeSpecTypes';
import type { WordRuleExtractionResult } from '../../shared/api/wordAuditTypes';

import { LatexPathPicker } from './LatexPathPicker';
import { joinWorkspacePath } from './latexPath';

const SPEC_SOURCE_EXTENSIONS = ['docx', 'txt', 'md'];

function formatTimestamp(value: number): string {
  if (!value) return '—';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

export interface OfficeSpecLibraryProps {
  workspacePath?: string | null;
}

export function OfficeSpecLibrary({ workspacePath }: OfficeSpecLibraryProps) {
  const [specs, setSpecs] = useState<OfficeSpecDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // 提取 → 保存为新规范书
  const [sourcePath, setSourcePath] = useState('');
  const [useLlm, setUseLlm] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [draft, setDraft] = useState<WordRuleExtractionResult | null>(null);
  const [draftName, setDraftName] = useState('');
  const [makeDefault, setMakeDefault] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);

  // 引用已有规则包快速创建
  const [packRefName, setPackRefName] = useState('');
  const [packRefId, setPackRefId] = useState('general-quality');
  const [creatingRef, setCreatingRef] = useState(false);

  // 文档级绑定
  const [bindDocId, setBindDocId] = useState('');
  const [bindSpecId, setBindSpecId] = useState('');
  const [binding, setBinding] = useState(false);
  const [bindingMessage, setBindingMessage] = useState<string | null>(null);

  const canUse = Boolean(workspacePath && workspacePath.trim());
  const hasDefault = specs.some((spec) => spec.is_default);

  const refresh = useCallback(async () => {
    if (!workspacePath) {
      setSpecs([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await officeApi.listSpecs({ workspacePath });
      setSpecs(result.specs);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [workspacePath]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleActivate = async (specId: string) => {
    if (!workspacePath) return;
    setBusyId(specId);
    setError(null);
    setMessage(null);
    try {
      const activated = await officeApi.activateSpec(specId, workspacePath);
      setMessage(`「${activated.name}」已设为工作区默认规范书`);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const handleClearDefault = async () => {
    if (!workspacePath) return;
    setBusyId('__clear__');
    setError(null);
    setMessage(null);
    try {
      await officeApi.clearDefaultSpec(workspacePath);
      setMessage('已清除工作区默认规范书');
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (specId: string) => {
    if (!workspacePath) return;
    if (pendingDeleteId !== specId) {
      setPendingDeleteId(specId);
      return;
    }
    setBusyId(specId);
    setError(null);
    setMessage(null);
    try {
      await officeApi.deleteSpec(specId, workspacePath);
      setMessage('规范书已删除（规则包文件保留）');
      setPendingDeleteId(null);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const handleExtract = async () => {
    if (!workspacePath) return;
    if (!sourcePath.trim()) {
      setError('请先填写说明文件路径');
      return;
    }
    setExtracting(true);
    setError(null);
    setMessage(null);
    setDraft(null);
    try {
      const result = await officeApi.extractSpec({
        workspace_path: workspacePath,
        file_path: joinWorkspacePath(workspacePath, sourcePath),
        use_llm: useLlm,
      });
      setDraft(result);
      if (!draftName.trim()) {
        setDraftName(`${result.pack.name || '新规范书'}（导入）`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setExtracting(false);
    }
  };

  const handleSaveDraft = async () => {
    if (!draft || !workspacePath) return;
    if (!draftName.trim()) {
      setError('请填写规范书名称');
      return;
    }
    setSavingDraft(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await officeApi.createSpec({
        workspace_path: workspacePath,
        name: draftName.trim(),
        pack: draft.pack,
        source_file_path: joinWorkspacePath(workspacePath, sourcePath),
        is_default: makeDefault,
      });
      const ruleCount = saved.rulepack?.rules.length ?? draft.pack.rules.length;
      setMessage(`规范书「${saved.spec.name}」已创建（${ruleCount} 条规则）`);
      setDraft(null);
      setDraftName('');
      setSourcePath('');
      setMakeDefault(false);
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingDraft(false);
    }
  };

  const handleCreateFromRulepack = async () => {
    if (!workspacePath) return;
    if (!packRefName.trim() || !packRefId.trim()) {
      setError('请填写规范书名称与规则包 ID');
      return;
    }
    setCreatingRef(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await officeApi.createSpec({
        workspace_path: workspacePath,
        name: packRefName.trim(),
        rulepack_id: packRefId.trim(),
      });
      setMessage(`规范书「${saved.spec.name}」已创建（引用规则包 ${saved.spec.rulepack_id}）`);
      setPackRefName('');
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreatingRef(false);
    }
  };

  const handleBind = async (specId: string | null) => {
    if (!workspacePath) return;
    if (!bindDocId.trim()) {
      setError('请先填写要绑定的文档 ID');
      return;
    }
    setBinding(true);
    setError(null);
    setBindingMessage(null);
    try {
      const result = await officeApi.bindDocSpec(bindDocId.trim(), {
        workspacePath,
        specId,
      });
      if (result.spec_id && result.effective_spec) {
        setBindingMessage(
          `文档 ${result.doc_id} 已绑定「${result.effective_spec.name}」`,
        );
      } else if (result.effective_spec) {
        setBindingMessage(
          `文档 ${result.doc_id} 已解绑，跟随工作区默认「${result.effective_spec.name}」`,
        );
      } else {
        setBindingMessage(`文档 ${result.doc_id} 已解绑，当前无生效规范书`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBinding(false);
    }
  };

  return (
    <section
      className="rounded-lg border border-border bg-bg-subtle p-4 flex flex-col gap-3"
      data-testid="office-spec-library"
    >
      <div>
        <h2 className="text-base font-medium text-text">格式规范书库</h2>
        <p className="text-xs text-muted mt-1">
          从投稿规范、写作要求等说明文件提取规则，绑定到工作区或单个文档；
          AI 审校会先跑规范书规则，再补充 LLM 语义建议。
        </p>
      </div>

      {!canUse ? (
        <p className="text-xs text-muted" data-testid="office-spec-no-workspace">
          请先在上方绑定工作区，再管理规范书。
        </p>
      ) : (
        <>
          {error ? (
            <p className="text-xs text-error" data-testid="office-spec-error">
              {error}
            </p>
          ) : null}
          {message ? (
            <p className="text-xs text-success" data-testid="office-spec-message">
              {message}
            </p>
          ) : null}

          <div className="flex flex-col gap-2" data-testid="office-spec-list">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-text">工作区规范书</span>
              <div className="flex items-center gap-2">
                {hasDefault ? (
                  <button
                    type="button"
                    onClick={() => void handleClearDefault()}
                    disabled={busyId !== null}
                    className="px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
                    data-testid="office-spec-clear-default"
                  >
                    清除默认
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => void refresh()}
                  disabled={loading}
                  className="px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
                  data-testid="office-spec-refresh"
                >
                  刷新
                </button>
              </div>
            </div>

            {loading ? (
              <p className="text-xs text-muted" data-testid="office-spec-loading">
                加载中…
              </p>
            ) : specs.length === 0 ? (
              <p className="text-xs text-muted" data-testid="office-spec-empty">
                暂无规范书。可在下方从说明文件提取，或引用已有规则包创建。
              </p>
            ) : (
              <ul className="flex flex-col divide-y divide-border rounded border border-border bg-bg">
                {specs.map((spec) => (
                  <li
                    key={spec.id}
                    className="px-3 py-2 flex items-center gap-3"
                    data-testid={`office-spec-row-${spec.id}`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-text truncate">{spec.name}</span>
                        {spec.is_default ? (
                          <span
                            className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-xs"
                            data-testid={`office-spec-default-badge-${spec.id}`}
                          >
                            工作区默认
                          </span>
                        ) : null}
                      </div>
                      <div className="text-xs text-muted mt-0.5 truncate">
                        规则包 {spec.rulepack_id} · 更新于 {formatTimestamp(spec.updated_at)}
                        {spec.source_file_path ? ` · 来源 ${spec.source_file_path}` : ''}
                      </div>
                    </div>
                    {!spec.is_default ? (
                      <button
                        type="button"
                        onClick={() => void handleActivate(spec.id)}
                        disabled={busyId !== null}
                        className="shrink-0 px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
                        data-testid={`office-spec-activate-${spec.id}`}
                      >
                        设为默认
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => void handleDelete(spec.id)}
                      disabled={busyId !== null}
                      className="shrink-0 px-2 py-1 rounded border border-border text-xs text-error hover:bg-bg-hover disabled:opacity-50"
                      data-testid={`office-spec-delete-${spec.id}`}
                    >
                      {pendingDeleteId === spec.id ? '确认删除' : '删除'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div
            className="border-t border-border pt-3 flex flex-col gap-2"
            data-testid="office-spec-extract"
          >
            <span className="text-sm font-medium text-text">从说明文件新建规范书</span>
            <LatexPathPicker
              value={sourcePath}
              onChange={setSourcePath}
              title="选择说明文件"
              extensions={SPEC_SOURCE_EXTENSIONS}
              placeholder="例如 docs/投稿规范.docx（相对工作区或绝对路径）"
              testId="office-spec-extract-path"
            />
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1 text-xs text-text-secondary">
                <input
                  type="checkbox"
                  checked={useLlm}
                  onChange={(event) => setUseLlm(event.target.checked)}
                  data-testid="office-spec-extract-use-llm"
                />
                启用 LLM 辅助提取
              </label>
              <button
                type="button"
                onClick={() => void handleExtract()}
                disabled={extracting}
                className="px-3 py-1.5 rounded bg-primary text-text-inverse text-sm hover:bg-primary-hover disabled:opacity-50"
                data-testid="office-spec-extract-run"
              >
                {extracting ? '提取中…' : '提取规则草稿'}
              </button>
            </div>

            {draft ? (
              <div
                className="rounded border border-border bg-bg p-3 flex flex-col gap-2"
                data-testid="office-spec-draft"
              >
                <p className="text-xs text-text-secondary">
                  已提取 {draft.pack.rules.length} 条规则
                  {draft.summary.warnings > 0 ? ` · ${draft.summary.warnings} 条警告` : ''}
                </p>
                <input
                  className="rounded border border-border bg-bg px-2 py-1 text-sm"
                  placeholder="规范书名称"
                  value={draftName}
                  onChange={(event) => setDraftName(event.target.value)}
                  data-testid="office-spec-draft-name"
                />
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-1 text-xs text-text-secondary">
                    <input
                      type="checkbox"
                      checked={makeDefault}
                      onChange={(event) => setMakeDefault(event.target.checked)}
                      data-testid="office-spec-draft-default"
                    />
                    设为工作区默认
                  </label>
                  <button
                    type="button"
                    onClick={() => void handleSaveDraft()}
                    disabled={savingDraft}
                    className="px-3 py-1.5 rounded bg-primary text-text-inverse text-sm hover:bg-primary-hover disabled:opacity-50"
                    data-testid="office-spec-draft-save"
                  >
                    {savingDraft ? '保存中…' : '保存为新规范书'}
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          <div
            className="border-t border-border pt-3 flex flex-col gap-2"
            data-testid="office-spec-from-pack"
          >
            <span className="text-sm font-medium text-text">引用已有规则包创建</span>
            <div className="flex flex-wrap items-center gap-2">
              <input
                className="min-w-40 flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
                placeholder="规范书名称"
                value={packRefName}
                onChange={(event) => setPackRefName(event.target.value)}
                data-testid="office-spec-ref-name"
              />
              <input
                className="min-w-40 flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
                placeholder="规则包 ID（如 general-quality）"
                value={packRefId}
                onChange={(event) => setPackRefId(event.target.value)}
                data-testid="office-spec-ref-pack-id"
              />
              <button
                type="button"
                onClick={() => void handleCreateFromRulepack()}
                disabled={creatingRef}
                className="px-3 py-1.5 rounded border border-border text-sm text-text-secondary hover:bg-bg-hover disabled:opacity-50"
                data-testid="office-spec-ref-create"
              >
                {creatingRef ? '创建中…' : '创建'}
              </button>
            </div>
          </div>

          <div
            className="border-t border-border pt-3 flex flex-col gap-2"
            data-testid="office-spec-bind"
          >
            <span className="text-sm font-medium text-text">为单个文档指定规范书</span>
            <p className="text-xs text-muted">
              文档级绑定优先于工作区默认；解绑后跟随工作区默认。
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                className="min-w-40 flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
                placeholder="文档 ID"
                value={bindDocId}
                onChange={(event) => setBindDocId(event.target.value)}
                data-testid="office-spec-bind-doc-id"
              />
              <select
                className="min-w-40 flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
                value={bindSpecId}
                onChange={(event) => setBindSpecId(event.target.value)}
                data-testid="office-spec-bind-spec-id"
              >
                <option value="">（解绑 / 跟随工作区默认）</option>
                {specs.map((spec) => (
                  <option key={spec.id} value={spec.id}>
                    {spec.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void handleBind(bindSpecId || null)}
                disabled={binding}
                className="px-3 py-1.5 rounded bg-primary text-text-inverse text-sm hover:bg-primary-hover disabled:opacity-50"
                data-testid="office-spec-bind-run"
              >
                {binding ? '绑定中…' : bindSpecId ? '绑定' : '解绑'}
              </button>
            </div>
            {bindingMessage ? (
              <p className="text-xs text-success" data-testid="office-spec-bind-message">
                {bindingMessage}
              </p>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}
