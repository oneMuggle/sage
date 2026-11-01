/**
 * WordRuleExtractionPanel (M3c) — 规范/范本 → 规则包复核与保存。
 *
 * 选择规范/范本文档 → 抽取候选规则 → 查看来源、置信度与冲突 →
 * 勾选启用项 → 保存为工作区规则包。抽取本身是只读的；只有「保存」写文件。
 *
 * 样式与交互沿用 LatexAuditPanel（中文文案、data-testid、无全局状态）。
 */

import { useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type { WordRuleExtractionResult, WordRulePack } from '../../shared/api/wordAuditTypes';

import { LatexPathPicker } from './LatexPathPicker';
import { joinWorkspacePath } from './latexPath';

const EXTRACT_EXTENSIONS = ['docx', 'txt', 'md'];
const TEMPLATE_EXTENSIONS = ['docx'];

function confidenceLabel(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export interface WordRuleExtractionPanelProps {
  workspacePath?: string | null;
}

export function WordRuleExtractionPanel({ workspacePath }: WordRuleExtractionPanelProps) {
  const [filePath, setFilePath] = useState('');
  const [fileType, setFileType] = useState<'spec' | 'template'>('spec');
  const [packId, setPackId] = useState('extracted-pack');
  const [packName, setPackName] = useState('');
  const [result, setResult] = useState<WordRuleExtractionResult | null>(null);
  const [disabledRuleIds, setDisabledRuleIds] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const canUse = Boolean(workspacePath && workspacePath.trim());
  const enabledCount = result
    ? result.pack.rules.filter((rule) => !disabledRuleIds.has(rule.id)).length
    : 0;

  const toggleRule = (ruleId: string) => {
    setDisabledRuleIds((previous) => {
      const next = new Set(previous);
      if (next.has(ruleId)) {
        next.delete(ruleId);
      } else {
        next.add(ruleId);
      }
      return next;
    });
  };

  const toggleAll = () => {
    if (!result) return;
    if (enabledCount === 0) {
      setDisabledRuleIds(new Set());
    } else {
      setDisabledRuleIds(new Set(result.pack.rules.map((rule) => rule.id)));
    }
  };

  const handleExtract = async () => {
    if (!canUse || !filePath.trim()) {
      setError('请先绑定工作区并填写规范/范本路径');
      return;
    }
    setBusy(true);
    setError(null);
    setSaveMessage(null);
    setSaveError(null);
    try {
      const data = await officeApi.extractWordRules({
        workspace_path: workspacePath!,
        file_path: joinWorkspacePath(workspacePath!, filePath),
        file_type: fileType,
        pack_id: packId.trim() || 'extracted-pack',
        ...(packName.trim() ? { pack_name: packName.trim() } : {}),
      });
      setResult(data);
      setDisabledRuleIds(new Set());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleSave = async () => {
    if (!result || !canUse) return;
    const rules = result.pack.rules.filter((rule) => !disabledRuleIds.has(rule.id));
    if (rules.length === 0) {
      setSaveError('至少保留一条启用规则');
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const pack: WordRulePack = { ...result.pack, rules };
      const saved = await officeApi.saveExtractedRulePack({
        workspace_path: workspacePath!,
        pack,
      });
      setSaveMessage(`已保存规则包 ${saved.pack.id}（${saved.pack.rules.length} 条）`);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className="flex flex-col gap-3 rounded border border-border p-4"
      data-testid="word-rule-extraction-panel"
    >
      <header>
        <h2 className="text-base font-semibold">Word 规则抽取</h2>
        <p className="text-xs text-muted">
          从规范文档条文或 .docx 范本主导值抽取候选规则；复核来源与置信度后保存为工作区规则包
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={fileType}
          onChange={(event) => setFileType(event.target.value as 'spec' | 'template')}
          data-testid="word-rule-extract-type"
          aria-label="抽取类型"
          className="rounded border border-border bg-surface px-2 py-1 text-xs"
        >
          <option value="spec">规范文档</option>
          <option value="template">范本模板</option>
        </select>
        <LatexPathPicker
          value={filePath}
          onChange={setFilePath}
          title={fileType === 'spec' ? '选择规范文档' : '选择范本模板'}
          extensions={fileType === 'template' ? TEMPLATE_EXTENSIONS : EXTRACT_EXTENSIONS}
          placeholder={fileType === 'spec' ? 'spec.docx / spec.txt' : 'template.docx'}
          testId="word-rule-extract-path"
          className="min-w-[16rem] flex-1"
        />
        <input
          value={packId}
          onChange={(event) => setPackId(event.target.value)}
          placeholder="规则包 id"
          aria-label="规则包 id"
          data-testid="word-rule-extract-pack-id"
          className="w-36 rounded border border-border bg-bg px-2 py-1 text-xs"
        />
        <input
          value={packName}
          onChange={(event) => setPackName(event.target.value)}
          placeholder="规则包名称（可选）"
          aria-label="规则包名称"
          data-testid="word-rule-extract-pack-name"
          className="w-44 rounded border border-border bg-bg px-2 py-1 text-xs"
        />
        <button
          type="button"
          onClick={() => void handleExtract()}
          disabled={busy || !canUse}
          data-testid="word-rule-extract-run"
          className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
        >
          {busy ? '抽取中…' : '抽取规则'}
        </button>
      </div>

      {!canUse && (
        <p className="text-xs text-muted" data-testid="word-rule-extract-no-workspace">
          请先绑定工作区再抽取规则。
        </p>
      )}

      {error && (
        <p className="text-xs text-error" data-testid="word-rule-extract-error">
          {error}
        </p>
      )}

      {result && (
        <>
          <div
            className="flex flex-wrap items-center gap-2 text-xs"
            data-testid="word-rule-extract-summary"
          >
            <span className={result.ok ? 'text-success' : 'text-warning'}>
              {result.ok ? '抽取完成' : '未识别到规则'}
            </span>
            <span className="text-muted">
              {result.summary.rules} 条规则 · {result.summary.conflicts} 个冲突 ·{' '}
              {result.summary.warnings} 个警告
            </span>
            <span className="text-muted">{result.source_path}</span>
          </div>

          {result.warnings.length > 0 && (
            <ul className="text-xs text-muted" data-testid="word-rule-extract-warnings">
              {result.warnings.map((warning, index) => (
                <li key={`${warning.code}-${index}`}>
                  {warning.code}: {warning.message}
                </li>
              ))}
            </ul>
          )}

          {result.conflicts.length > 0 && (
            <ul
              className="rounded border border-warning/40 bg-warning/10 p-2 text-xs text-warning"
              data-testid="word-rule-extract-conflicts"
            >
              {result.conflicts.map((conflict, index) => (
                <li key={`${conflict.kind}-${index}`}>
                  {conflict.kind}: {conflict.message}（{conflict.rule_ids.join(', ')}）
                </li>
              ))}
            </ul>
          )}

          {result.candidates.length === 0 ? (
            <p className="text-xs text-muted" data-testid="word-rule-extract-empty">
              没有候选规则。
            </p>
          ) : (
            <ul className="flex flex-col gap-2" data-testid="word-rule-extract-candidates">
              {result.candidates.map((candidate, index) => {
                const rule = candidate.rule;
                const enabled = !disabledRuleIds.has(rule.id);
                return (
                  <li
                    key={rule.id}
                    data-testid={`word-rule-extract-candidate-${index}`}
                    className={`rounded border p-2 ${
                      enabled ? 'border-border' : 'border-border opacity-60'
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <label className="flex items-center gap-1 text-xs">
                        <input
                          type="checkbox"
                          checked={enabled}
                          onChange={() => toggleRule(rule.id)}
                          data-testid={`word-rule-extract-enable-${index}`}
                          aria-label={`启用 ${rule.title}`}
                        />
                        启用
                      </label>
                      <span className="text-sm font-medium">{rule.title}</span>
                      <code className="text-ui-2xs text-muted">{rule.id}</code>
                      <span className="rounded border border-border px-1.5 py-0.5 text-ui-2xs text-text-secondary">
                        置信度 {confidenceLabel(candidate.confidence)}
                      </span>
                      {candidate.conflict_group && (
                        <span className="rounded border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-ui-2xs text-warning">
                          冲突
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted">
                      {candidate.source_excerpt || rule.source || '无来源说明'}
                    </p>
                    <code className="mt-1 block break-all text-ui-2xs text-text-secondary">
                      {JSON.stringify(rule.params)}
                    </code>
                  </li>
                );
              })}
            </ul>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={toggleAll}
              data-testid="word-rule-extract-toggle-all"
              className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover"
            >
              {enabledCount === 0 ? '全部启用' : '全部停用'}
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || enabledCount === 0}
              data-testid="word-rule-extract-save"
              className="rounded border border-primary/40 bg-primary/10 px-2 py-1 text-xs text-primary hover:bg-primary/20 disabled:opacity-50"
            >
              {saving ? '保存中…' : `保存规则包（${enabledCount} 条）`}
            </button>
            {saveMessage && (
              <span className="text-xs text-success" data-testid="word-rule-extract-save-ok">
                {saveMessage}
              </span>
            )}
            {saveError && (
              <span className="text-xs text-error" data-testid="word-rule-extract-save-error">
                {saveError}
              </span>
            )}
          </div>
        </>
      )}
    </section>
  );
}
