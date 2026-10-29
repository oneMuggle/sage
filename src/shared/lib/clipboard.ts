import { toast } from 'sonner';

/**
 * 统一剪贴板写入。
 *
 * - 优先 `navigator.clipboard.writeText`；失败（非安全上下文 / 权限拒绝 /
 *   jsdom 等）回退到临时 textarea + `document.execCommand('copy')`。
 * - 反馈文案由调用方通过 i18n 传入，工具本身不绑定语言。
 */
export interface CopyToClipboardOptions {
  successMessage?: string;
  errorMessage?: string;
}

export function copyTextFallback(text: string): boolean {
  if (typeof document === 'undefined') return false;
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.top = '-9999px';
  area.style.opacity = '0';
  document.body.appendChild(area);
  try {
    area.select();
    return typeof document.execCommand === 'function' && document.execCommand('copy');
  } catch {
    return false;
  } finally {
    document.body.removeChild(area);
  }
}

export async function copyToClipboard(
  text: string,
  options: CopyToClipboardOptions = {},
): Promise<boolean> {
  let ok = false;
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      ok = true;
    }
  } catch {
    ok = false;
  }
  if (!ok) ok = copyTextFallback(text);

  if (ok) {
    if (options.successMessage) toast.success(options.successMessage);
  } else if (options.errorMessage) {
    toast.error(options.errorMessage);
  }
  return ok;
}
