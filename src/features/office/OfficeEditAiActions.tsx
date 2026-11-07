/**
 * OfficeEditAiActions (P2 M6) — 编辑预览对话框里的 AI 改写按钮组。
 *
 * 四个按钮对应 aiApi.rewrite 的四种 instruction：rewrite / polish /
 * expand / condense。每次点击读取调用方传入的 `getCurrentText` 作为待改写
 * 文本，成功后把结果交给 `onResult` 回填（对话框本身可撤销）。
 *
 * 单一 `busy` 状态：请求期间禁用全部按钮，并显示 i18n 的“生成中…”。
 * 失败时在组件内用 role="alert" 显示 `office.ai.sidebar.request_failed`
 * 文案，不向上抛出；下一次点击清空上次的错误。
 *
 * R19 裁定 — 字段映射：
 * OfficeEditPreviewDialog 没有 `currentDocText` state，它是一组 op 参数
 * 表单 (`compose: ComposeState`)。下方 `officeEditAiProps` 把
 * `doc_type → compose.<kindField> → 主文本字段` 的映射封装成一个 props
 * 工厂，供对话框用一行 JSX 完成接线；同时把对话框总行数控制在 800 行
 * 架构门禁之下。
 */

import { useState } from 'react';

import { aiApi, type AiRewriteRequest } from '../../shared/api/aiApi';
import { fillTemplate } from '../../shared/lib/fillTemplate';
import { useI18n } from '../../shared/lib/i18n';

export type OfficeEditAiInstruction = 'rewrite' | 'polish' | 'expand' | 'condense';

export interface OfficeEditAiActionsProps {
  workspacePath: string;
  documentId: string;
  /** 读取当前编辑框内容的快照（用于构造请求）。 */
  getCurrentText: () => string;
  /** 结果回填到编辑框。 */
  onResult: (text: string) => void;
  disabled?: boolean;
}

export type OfficeEditAiTextFieldKey =
  | 'replace'
  | 'paragraphsText'
  | 'tableText'
  | 'commentText'
  | 'value'
  | 'rowsText'
  | 'slideTitle'
  | 'bulletsText'
  | 'notesText';

interface AiComposeSource {
  wordKind: string;
  excelKind: string;
  pptKind: string;
  replace: string;
  paragraphsText: string;
  tableText: string;
  commentText: string;
  value: string;
  rowsText: string;
  slideTitle: string;
  bulletsText: string;
  notesText: string;
}

const AI_FIELD_BY_KIND: Record<string, OfficeEditAiTextFieldKey | undefined> = {
  replace_text: 'replace',
  append_paragraphs: 'paragraphsText',
  set_table_cell: 'tableText',
  add_comment: 'commentText',
  set_cells: 'value',
  append_rows: 'rowsText',
  set_slide_title: 'slideTitle',
  set_slide_bullets: 'bulletsText',
  set_slide_notes: 'notesText',
};

/** 当前 op kind → 主文本字段（R19 裁定映射；其余 op 返回 null）。 */
// eslint-disable-next-line react-refresh/only-export-components
export function aiFieldForKind(
  docType: string,
  compose: AiComposeSource,
): OfficeEditAiTextFieldKey | null {
  const kind =
    docType === 'word'
      ? compose.wordKind
      : docType === 'excel'
        ? compose.excelKind
        : docType === 'ppt'
          ? compose.pptKind
          : null;
  return kind ? (AI_FIELD_BY_KIND[kind] ?? null) : null;
}

/**
 * 把 `getCurrentText` / `onResult` 绑定到 compose 主文本字段。
 * 对话框只需一行 JSX 接入，净增行数受控（≤ 800 行架构门禁）。
 */
// eslint-disable-next-line react-refresh/only-export-components
export function officeEditAiProps(
  workspacePath: string,
  documentId: string,
  docType: string,
  compose: AiComposeSource,
  setField: (key: OfficeEditAiTextFieldKey) => (value: string) => void,
): OfficeEditAiActionsProps {
  const field = aiFieldForKind(docType, compose);
  return {
    workspacePath,
    documentId,
    getCurrentText: () => (field ? compose[field] : ''),
    onResult: (text) => {
      if (field) setField(field)(text);
    },
  };
}

const INSTRUCTIONS: OfficeEditAiInstruction[] = ['rewrite', 'polish', 'expand', 'condense'];

export function OfficeEditAiActions({
  workspacePath,
  documentId,
  getCurrentText,
  onResult,
  disabled = false,
}: OfficeEditAiActionsProps): JSX.Element {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  const run = async (instruction: OfficeEditAiInstruction) => {
    const text = getCurrentText();
    if (!text.trim() || busy) return;
    setBusy(true);
    setErrorText(null);
    try {
      const request: AiRewriteRequest = { workspacePath, documentId, text, instruction };
      const result = await aiApi.rewrite(request);
      onResult(result.result);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setErrorText(fillTemplate(t('office.ai.sidebar.request_failed'), { message }));
    } finally {
      setBusy(false);
    }
  };

  const isDisabled = disabled || busy || !getCurrentText().trim();

  return (
    <div className="space-y-2" data-testid="office-edit-ai-actions">
      <div className="flex flex-wrap items-center gap-2">
        {INSTRUCTIONS.map((instruction) => (
          <button
            key={instruction}
            type="button"
            onClick={() => void run(instruction)}
            disabled={isDisabled}
            className="px-2.5 py-1 text-xs border border-border rounded bg-surface text-text hover:bg-bg-hover disabled:opacity-50"
            data-testid={`office-edit-ai-${instruction}`}
          >
            {t(`office.ai.edit.${instruction}`)}
          </button>
        ))}
        {busy && (
          <span className="text-xs text-muted" data-testid="office-edit-ai-thinking">
            {t('office.ai.sidebar.thinking')}
          </span>
        )}
      </div>
      {errorText && (
        <p role="alert" className="text-xs text-error" data-testid="office-edit-ai-error">
          {errorText}
        </p>
      )}
    </div>
  );
}
