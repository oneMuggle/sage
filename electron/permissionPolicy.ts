// electron/permissionPolicy.ts
//
// 默认拒绝权限请求策略（feat/rich-preview-rendering）——为 default session 设置
// setPermissionRequestHandler 与 setPermissionCheckHandler，仅对白名单权限放行。
//
// 为什么挂在 session 而不是 webContents：
// - webContents 级 handler 优先级高于 session 级。若用 app.on('web-contents-created')
//   逐个安装，会覆盖 agentBrowserHost / browserPanel 在各自 partition 上设置的
//   "全部拒绝"，反而给内置浏览器放行 clipboard/notifications。
// - session 级 handler 只作用于 default session（主窗口/启动屏/独立 artifact 窗口
//   以及其中的 srcdoc iframe）。独立 partition 的严格策略不受影响，保持原样。
import { session } from 'electron';

const ALLOWED_PERMISSIONS = new Set([
  'clipboard-read',
  'clipboard-sanitized-write',
  'notifications',
]);

export function installPermissionPolicy(): void {
  const defaultSession = session.defaultSession;
  defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(ALLOWED_PERMISSIONS.has(permission));
  });
  defaultSession.setPermissionCheckHandler((_wc, permission) => {
    return ALLOWED_PERMISSIONS.has(permission);
  });
}
