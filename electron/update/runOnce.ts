/**
 * Windows RunOnce 注册表助手 (2026-09, update-install-rollback-r1-plan §B)。
 *
 * 背景: Windows 锁定运行中可执行文件所在目录, 升级前的目录交换必须推迟到
 * 进程退出后。此前 `.prepare-rollback.bat` 被写入磁盘但没有任何机制执行它。
 * RunOnce (`HKCU\...\RunOnce`) 在下一次登录时执行一次并自动清除, 是桌面
 * 应用无需服务/无需管理员的标准做法。
 *
 * 全部操作 best-effort: 失败只记日志, 绝不阻断升级主流程。
 */
import { spawn } from 'child_process';

const RUNONCE_KEY = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce';
const VALUE_NAME = 'SageRollback';

/** 注册一条 RunOnce 命令 (下次用户登录时执行一次)。 */
export function registerRunOnceCommand(command: string): Promise<void> {
  return new Promise((resolve) => {
    try {
      const child = spawn(
        'reg',
        ['add', RUNONCE_KEY, '/v', VALUE_NAME, '/t', 'REG_SZ', '/d', command, '/f'],
        { windowsHide: true },
      );
      child.on('exit', () => resolve());
      child.on('error', () => resolve());
    } catch {
      resolve();
    }
  });
}

/** 删除 RunOnce 中的 SageRollback 值 (交换完成后调用)。 */
export function clearRunOnce(): Promise<void> {
  return new Promise((resolve) => {
    try {
      const child = spawn(
        'reg',
        ['delete', RUNONCE_KEY, '/v', VALUE_NAME, '/f'],
        { windowsHide: true },
      );
      child.on('exit', () => resolve());
      child.on('error', () => resolve());
    } catch {
      resolve();
    }
  });
}
