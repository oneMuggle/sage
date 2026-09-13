/**
 * TemplateFillDialog — R29：Prompt 模板 {{变量}} 填充对话框。
 *
 * 选中含 {{变量}} 占位的模板时弹出，按占位符逐项填写后确认，
 * 以解析后的完整文本回填输入框。无占位的模板不经过此对话框。
 * 抽取/解析逻辑为纯函数（extractTemplateVars / resolveTemplate），
 * 可独立单测。
 */

import { useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';

/** 抽取模板中的 {{变量}} 占位（按出现顺序去重）。 */
export function extractTemplateVars(content: string): string[] {
  const seen = new Set<string>();
  const vars: string[] = [];
  const re = /\{\{([^{}]+)\}\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    const name = m[1].trim();
    if (name && !seen.has(name)) {
      seen.add(name);
      vars.push(name);
    }
  }
  return vars;
}

// R31: 变量记忆 —— 每个模板内容（按内容哈希）记住上次填写值，存 localStorage。
// 键 = sage:tplfill:<djb2(content)>；读写失败静默降级（隐私模式等）。
function tplStorageKey(content: string): string {
  let hash = 5381;
  for (let i = 0; i < content.length; i++) {
    hash = ((hash << 5) + hash + content.charCodeAt(i)) | 0;
  }
  return `sage:tplfill:${hash >>> 0}`;
}

export function loadRememberedValues(content: string): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(tplStorageKey(content));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, string>) : {};
  } catch {
    return {};
  }
}

export function saveRememberedValues(
  content: string,
  values: Record<string, string>,
): void {
  try {
    // 只记非空值 —— 清空输入=遗忘该变量
    const filled = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v.trim() !== ''),
    );
    window.localStorage.setItem(tplStorageKey(content), JSON.stringify(filled));
  } catch {
    // ignore — localStorage 不可用时静默
  }
}

/** 用填写的值解析模板；留空的变量保留 {{占位}} 原样。 */
export function resolveTemplate(
  content: string,
  values: Record<string, string>,
): string {
  return content.replace(/\{\{([^{}]+)\}\}/g, (whole, rawName: string) => {
    const name = rawName.trim();
    const value = values[name];
    return value !== undefined && value !== '' ? value : whole;
  });
}

interface TemplateFillDialogProps {
  content: string;
  onConfirm: (resolved: string) => void;
  onCancel: () => void;
}

export function TemplateFillDialog({ content, onConfirm, onCancel }: TemplateFillDialogProps) {
  const { t } = useI18n();
  const vars = extractTemplateVars(content);
  const [values, setValues] = useState<Record<string, string>>(() =>
    loadRememberedValues(content),
  );

  const handleConfirm = () => {
    saveRememberedValues(content, values);
    onConfirm(resolveTemplate(content, values));
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      data-testid="tpl-fill-dialog"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md p-4 rounded-radius-md border border-border bg-surface space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-semibold text-text">{t('tplfill.title')}</h3>
        <p className="text-xs text-text-secondary">{t('tplfill.subtitle')}</p>
        {vars.map((v) => (
          <label key={v} className="block text-xs text-text-secondary">
            {v}
            <input
              data-testid={`tplfill-input-${v}`}
              autoFocus={vars[0] === v}
              value={values[v] ?? ''}
              onChange={(e) => setValues((prev) => ({ ...prev, [v]: e.target.value }))}
              className="mt-1 w-full px-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text"
            />
          </label>
        ))}
        {vars.length === 0 && (
          <p className="text-xs text-text-secondary">{t('tplfill.no_vars')}</p>
        )}
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="px-2.5 py-1 text-xs rounded-radius-sm border border-border hover:bg-bg-hover"
          >
            {t('tplfill.cancel')}
          </button>
          <button
            type="button"
            data-testid="tplfill-confirm"
            onClick={handleConfirm}
            className="px-2.5 py-1 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover"
          >
            {t('tplfill.confirm')}
          </button>
        </div>
      </div>
    </div>
  );
}
