import { describe, expect, it, vi } from 'vitest';

import {
  buildEditableContextMenuTemplate,
  registerEditableContextMenu,
  type EditableContextParams,
} from '../contextMenu';

const mocks = vi.hoisted(() => ({
  popup: vi.fn(),
  buildFromTemplate: vi.fn(),
  fromWebContents: vi.fn(() => ({ id: 1 })),
  app: { isPackaged: false },
}));

vi.mock('electron', () => ({
  Menu: {
    buildFromTemplate: mocks.buildFromTemplate,
  },
  BrowserWindow: {
    fromWebContents: mocks.fromWebContents,
  },
  app: mocks.app,
}));

mocks.buildFromTemplate.mockImplementation((template: unknown) => ({
  template,
  popup: mocks.popup,
}));

function params(overrides: Partial<EditableContextParams> = {}): EditableContextParams {
  return {
    isEditable: true,
    x: 12,
    y: 34,
    editFlags: {
      canUndo: true,
      canRedo: false,
      canCut: true,
      canCopy: true,
      canPaste: false,
      canSelectAll: true,
    },
    ...overrides,
  };
}

type MenuItem = {
  role?: string;
  type?: string;
  label?: string;
  enabled?: boolean;
  click?: () => void;
};

function fakeWebContents() {
  let handler: ((event: unknown, p: EditableContextParams) => void) | null = null;
  const webContents = {
    on: vi.fn((name: string, fn: typeof handler) => {
      if (name === 'context-menu') handler = fn;
    }),
    inspectElement: vi.fn(),
  };
  return {
    webContents,
    emitContextMenu(p: EditableContextParams) {
      handler?.({ preventDefault: vi.fn() }, p);
    },
  };
}

describe('buildEditableContextMenuTemplate', () => {
  it('maps edit flags onto role-based native items', () => {
    const template = buildEditableContextMenuTemplate(params()) as MenuItem[];

    expect(template.map((item) => item.role ?? item.type)).toEqual([
      'undo',
      'redo',
      'separator',
      'cut',
      'copy',
      'paste',
      'selectAll',
    ]);
    expect(template[0].enabled).toBe(true);
    expect(template[1].enabled).toBe(false);
    expect(template[5].enabled).toBe(false);
  });

  it('appends a dev-only inspect item with a working callback', () => {
    const onInspect = vi.fn();
    const template = buildEditableContextMenuTemplate(params(), {
      isDev: true,
      onInspect,
    }) as MenuItem[];

    const inspect = template.find((item) => item.label === '检查元素');
    expect(inspect).toBeDefined();
    inspect?.click?.();
    expect(onInspect).toHaveBeenCalledTimes(1);
  });

  it('omits the inspect item outside dev', () => {
    const template = buildEditableContextMenuTemplate(params()) as MenuItem[];
    expect(template.find((item) => item.label === '检查元素')).toBeUndefined();
  });
});

describe('registerEditableContextMenu', () => {
  it('ignores right clicks on non-editable content', () => {
    const { webContents, emitContextMenu } = fakeWebContents();
    registerEditableContextMenu(webContents as never, { isDev: false });

    emitContextMenu(params({ isEditable: false }));

    expect(mocks.buildFromTemplate).not.toHaveBeenCalled();
    expect(mocks.popup).not.toHaveBeenCalled();
  });

  it('pops the native menu for editable content', () => {
    const { webContents, emitContextMenu } = fakeWebContents();
    registerEditableContextMenu(webContents as never, { isDev: false });

    emitContextMenu(params());

    expect(mocks.buildFromTemplate).toHaveBeenCalledTimes(1);
    expect(mocks.popup).toHaveBeenCalledTimes(1);
    expect(mocks.popup.mock.calls[0][0]).toEqual({ window: { id: 1 } });
  });

  it('inspects the clicked coordinates from the dev item', () => {
    const { webContents, emitContextMenu } = fakeWebContents();
    registerEditableContextMenu(webContents as never, { isDev: true });

    emitContextMenu(params({ x: 77, y: 88 }));
    const template = mocks.buildFromTemplate.mock.calls.at(-1)?.[0] as MenuItem[];
    template.find((item) => item.label === '检查元素')?.click?.();

    expect(webContents.inspectElement).toHaveBeenCalledWith(77, 88);
  });
});
