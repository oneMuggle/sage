/**
 * ConfirmDialogHost (R3): confirmDialog() 服务的全局视图挂载点。
 *
 * 在 AppProviders 挂载一次; 所有 confirmDialog() 请求在这里以 Radix
 * Dialog 呈现 —— 焦点陷阱 / Esc 关闭 / 主题化样式, 替代阻塞式的
 * window.confirm。
 */
import { useEffect, useState } from 'react';

import { Button } from '../Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../Dialog';

import { resolveConfirm, subscribeConfirm, type ConfirmOptions } from './confirmService';

export function ConfirmDialogHost() {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);

  useEffect(() => subscribeConfirm(setOpts), []);

  // Esc / overlay 点击触发 Radix onOpenChange(false) → 视为取消
  return (
    <Dialog open={opts !== null} onOpenChange={(open) => !open && resolveConfirm(false)}>
      {opts && (
        <DialogContent showCloseButton={false} className="max-w-md">
          <DialogHeader>
            <DialogTitle>{opts.title}</DialogTitle>
            {opts.message && <DialogDescription>{opts.message}</DialogDescription>}
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => resolveConfirm(false)}>
              {opts.cancelLabel ?? '取消'}
            </Button>
            <Button
              variant={opts.danger ? 'danger' : 'primary'}
              onClick={() => resolveConfirm(true)}
            >
              {opts.confirmLabel ?? '确认'}
            </Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  );
}
