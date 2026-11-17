/**
 * 离线组件包（.sagepkg）设置文案。
 *
 * 独立分域，避免推高 chatAndSider 行数；聚合入口见 ../../zh.ts。
 */
export const zhComponents = {
  'settings.tab.components': '组件管理',
  'settings.components.title': '离线组件管理',
  'settings.components.desc':
    '导入管理员签名的 .sagepkg 离线组件包（模型、OCR 等），无需联网即可补装或修复。',
  'settings.components.import': '导入 .sagepkg',
  'settings.components.scan': '扫描组件包',
  'settings.components.refresh': '刷新',
  'settings.components.installed_title': '已安装组件',
  'settings.components.installed_empty': '尚未安装任何离线组件。',
  'settings.components.discovered_title': '发现的组件包',
  'settings.components.discovered_empty': '未发现可导入的组件包。',
  'settings.components.remove': '卸载',
  'settings.components.remove_confirm': '确认卸载组件「{name}」？删除后需要重新导入才能恢复。',
  'settings.components.import_success': '导入完成。请重启 Sage 后生效。',
  'settings.components.remove_success': '组件已卸载。',
  'settings.components.scan_success': '扫描完成，发现可导入的组件包。',
  'settings.components.scan_empty': '扫描完成，未发现组件包。',
  'settings.components.error': '组件操作失败，请查看日志或使用 Sage 修复工具。',
  'settings.components.unsupported': '组件管理仅在 Sage 桌面端可用。',
  'settings.components.importing': '正在导入组件包…',
  'settings.components.signature_ok': '签名已验证',
  'settings.components.security_note':
    '仅接受签名有效的组件包；生产终端不会执行 pip/npm。win7 组件包必须使用 Python 3.8 构建。',
} as const;
