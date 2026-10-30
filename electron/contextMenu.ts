import {
  app,
  BrowserWindow,
  Menu,
  type MenuItemConstructorOptions,
  type WebContents,
} from 'electron';

/**
 * 可编辑控件的原生右键菜单（剪切/复制/粘贴/全选/撤销/重做）。
 *
 * Electron 21 不提供浏览器默认右键菜单；文本框、CodeMirror、xterm 等
 * 可编辑区域交给 OS 原生菜单，避免在渲染层重造文本编辑语义。
 * 应用内的对象级菜单由渲染层 Radix ContextMenu 负责（非 editable 不处理）。
 *
 * 开发期（未打包）额外追加「检查元素」，便于调试。
 */

/** WebContents 'context-menu' 事件 params 中本模块关心的字段。 */
export interface EditableContextParams {
  isEditable: boolean;
  x: number;
  y: number;
  editFlags: {
    canUndo: boolean;
    canRedo: boolean;
    canCut: boolean;
    canCopy: boolean;
    canPaste: boolean;
    canSelectAll: boolean;
  };
}

export interface EditableContextMenuOptions {
  isDev?: boolean;
  /** 开发期「检查元素」回调（由注册方注入具体 webContents 与坐标）。 */
  onInspect?: () => void;
}

export function buildEditableContextMenuTemplate(
  params: EditableContextParams,
  options: EditableContextMenuOptions = {},
): MenuItemConstructorOptions[] {
  const flags = params.editFlags;
  const template: MenuItemConstructorOptions[] = [
    { role: 'undo', enabled: flags.canUndo },
    { role: 'redo', enabled: flags.canRedo },
    { type: 'separator' },
    { role: 'cut', enabled: flags.canCut },
    { role: 'copy', enabled: flags.canCopy },
    { role: 'paste', enabled: flags.canPaste },
    { role: 'selectAll', enabled: flags.canSelectAll },
  ];

  if (options.isDev) {
    template.push(
      { type: 'separator' },
      {
        label: '检查元素',
        click: () => options.onInspect?.(),
      },
    );
  }

  return template;
}

export function registerEditableContextMenu(
  webContents: WebContents,
  options: EditableContextMenuOptions = {},
): void {
  webContents.on('context-menu', (_event, params) => {
    if (!params.isEditable) return;

    const template = buildEditableContextMenuTemplate(params, {
      ...options,
      onInspect: () => webContents.inspectElement(params.x, params.y),
    });
    Menu.buildFromTemplate(template).popup({
      window: BrowserWindow.fromWebContents(webContents) ?? undefined,
    });
  });
}

/** 仅用于打包环境判断的单点封装，便于测试替身。 */
export function isDevEnvironment(): boolean {
  return !app.isPackaged;
}
