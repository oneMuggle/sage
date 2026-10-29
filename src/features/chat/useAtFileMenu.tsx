// src/features/chat/useAtFileMenu.tsx
//
// 共享的 `@` 文件/实体引用菜单逻辑 —— ChatInput（会话页）与
// WelcomeInputCard（新会话页）共用，避免两处实现漂移。
//
// 职责：
// - 根据光标位置解析当前 `@` 查询；
// - 渲染实体类型行（@memory:/@wiki:/@skill:/@agent:）与文件候选菜单；
// - 选中文件时把 `@<path> ` 插回输入框，选中 office 文档时导入为 ChatOfficeRef；
// - Esc 关闭时移除当前 `@` 查询。
import { useCallback, useEffect, type ReactNode } from 'react';

import type { AtFileSelection } from '../../shared/api/fileSearchClient';
import type { ChatOfficeRef } from '../../shared/api/types';
import { importOfficeReference } from '../office/importOfficeReference';

import { AtEntityMenu } from './AtEntityMenu';
import { AtFileMenu } from './AtFileMenu';
import { parseEntityRefQuery } from './entityRefs';
import { useAtFileQuery } from './useAtFileQuery';

export interface UseAtFileMenuOptions {
  /** 当前输入框内容 */
  value: string;
  /** 光标位置（0-based） */
  cursorPos: number;
  /** 写回输入框内容 */
  onChange: (next: string) => void;
  /** 写回光标位置（插入 token 后定位） */
  onCursorChange: (pos: number) => void;
  /** 工作区根路径（office 导入需要）；未绑定工作区时为 undefined */
  workspacePath?: string | null;
  /** 添加一个已解析的 office 引用（调用方负责去重） */
  addOfficeRef: (ref: ChatOfficeRef) => void;
  /**
   * `@` 查询激活时触发。新会话页借此懒创建草稿会话，使文件搜索拿到
   * 会话绑定的工作区；会话页不传。
   */
  onQueryActive?: (query: string) => void;
}

export interface UseAtFileMenuResult {
  /** 当前 `@` 查询（未激活时 query=null） */
  atQuery: ReturnType<typeof useAtFileQuery>;
  /** 可直接渲染到 InputCard 的 `atFileMenu` 节点 */
  atFileMenu: ReactNode;
}

export function useAtFileMenu({
  value,
  cursorPos,
  onChange,
  onCursorChange,
  workspacePath,
  addOfficeRef,
  onQueryActive,
}: UseAtFileMenuOptions): UseAtFileMenuResult {
  const atQuery = useAtFileQuery(value, cursorPos);
  const entityRef = parseEntityRefQuery(atQuery.query);

  useEffect(() => {
    if (atQuery.query !== null) onQueryActive?.(atQuery.query);
  }, [atQuery.query, onQueryActive]);

  /** 插入纯文本 `@<path> `，替换当前 @ 查询。 */
  const insertAtFilePath = useCallback(
    (filePath: string) => {
      if (atQuery.query === null) return;
      const newValue =
        value.slice(0, atQuery.startIdx) + '@' + filePath + ' ' + value.slice(atQuery.endIdx);
      onChange(newValue);
      onCursorChange(atQuery.startIdx + 1 + filePath.length + 1);
    },
    [value, atQuery, onChange, onCursorChange],
  );

  /** 把 `@kind:` 前缀写入输入框（光标停在冒号后，等待用户输入查询）。 */
  const insertEntityToken = useCallback(
    (token: string) => {
      if (atQuery.query === null) return;
      const newValue = value.slice(0, atQuery.startIdx) + token + value.slice(atQuery.endIdx);
      onChange(newValue);
      onCursorChange(atQuery.startIdx + token.length);
    },
    [value, atQuery, onChange, onCursorChange],
  );

  /** 移除当前 `@查询`，光标回到 @ 起始位置。 */
  const clearAtQuery = useCallback(() => {
    if (atQuery.query === null) return;
    const newValue = value.slice(0, atQuery.startIdx) + value.slice(atQuery.endIdx);
    onChange(newValue);
    onCursorChange(atQuery.startIdx);
  }, [value, atQuery, onChange, onCursorChange]);

  const handleAtFileSelect = useCallback(
    async (selection: AtFileSelection) => {
      if (selection.kind === 'file') {
        insertAtFilePath(selection.path);
        return;
      }
      if (selection.kind === 'office') {
        addOfficeRef(selection.ref);
        clearAtQuery();
        return;
      }
      // kind === 'office-import'
      // 先清掉输入框里的 `@查询`（菜单随之关闭），再异步导入；避免导入期间
      // 用户继续编辑导致基于旧 value 的切片误删文本。
      clearAtQuery();
      if (!workspacePath) {
        // 未绑定工作区 —— 不调用网关，菜单由调用方关闭即可。
        console.warn('[useAtFileMenu] Office import requires a bound workspace');
        return;
      }
      try {
        const ref = await importOfficeReference(workspacePath, selection.result);
        addOfficeRef(ref);
      } catch (e) {
        console.error('[useAtFileMenu] Office import failed', e);
      }
    },
    [workspacePath, insertAtFilePath, addOfficeRef, clearAtQuery],
  );

  const handleAtFileClose = clearAtQuery;

  const atFileMenu: ReactNode =
    atQuery.query !== null && entityRef === null ? (
      <>
        <AtEntityMenu query={atQuery.query} onSelect={(s) => insertEntityToken(s.token)} />
        <AtFileMenu
          query={atQuery.query}
          onSelect={(selection) => {
            void handleAtFileSelect(selection);
          }}
          onClose={handleAtFileClose}
        />
      </>
    ) : null;

  return { atQuery, atFileMenu };
}
