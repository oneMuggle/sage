/**
 * Promise 化确认弹窗服务 (R3): 替代 window.confirm。
 *
 * window.confirm 阻塞主线程、不适配主题、按钮不可本地化。本服务把
 * "await confirmDialog(opts)" 作为同步 confirm 的_drop-in_替代 —— 调用方
 * 只需把所在回调改成 async。UI 由 <ConfirmDialogHost/> 渲染 (挂在
 * AppProviders), 服务与视图通过订阅解耦, 便于单测。
 */

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** 危险操作: 确认按钮使用 error 色 */
  danger?: boolean;
}

interface ActiveConfirm {
  opts: ConfirmOptions;
  resolve: (v: boolean) => void;
}

type StateListener = (opts: ConfirmOptions | null) => void;

let active: ActiveConfirm | null = null;
const listeners = new Set<StateListener>();

function emit(): void {
  const snapshot = active?.opts ?? null;
  listeners.forEach((l) => l(snapshot));
}

export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    // 同一时刻只保留最后一次请求; 被顶掉的请求按取消结算, 不悬挂
    if (active) active.resolve(false);
    active = { opts, resolve };
    emit();
  });
}

export function resolveConfirm(value: boolean): void {
  if (!active) return;
  const { resolve } = active;
  active = null;
  emit();
  resolve(value);
}

export function subscribeConfirm(listener: StateListener): () => void {
  listeners.add(listener);
  listener(active?.opts ?? null);
  return () => {
    listeners.delete(listener);
  };
}
