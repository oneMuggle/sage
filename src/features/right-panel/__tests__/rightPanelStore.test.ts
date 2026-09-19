// src/features/right-panel/__tests__/rightPanelStore.test.ts
//
// right-panel R1 批次 A/B/C: 面板全局 store 单测 —— 持久化迁移、
// selectArtifact 副作用、未读基线、自动唤起守卫（当前会话/开关/已开）。

import { beforeEach, describe, expect, it } from 'vitest';

import { useStore } from '../../../shared/lib/store';
import { useArtifactEventsStore } from '../../artifacts/artifactEventsStore';
import {
  isArtifactAutoOpenEnabled,
  maybeAutoOpenArtifactPanel,
  setArtifactAutoOpenEnabled,
  useRightPanelStore,
} from '../rightPanelStore';

const SID = 'sess-rp1';

function resetAll() {
  localStorage.clear();
  useRightPanelStore.setState({
    open: false,
    tab: 'progress',
    maximized: false,
    selectedArtifactId: null,
    seenArtifactCount: {},
  });
  useArtifactEventsStore.setState({ counts: {} });
  useStore.setState({ currentSessionId: SID });
}

beforeEach(resetAll);

describe('rightPanelStore — 持久化', () => {
  it('setOpen 写 right-panel-open', () => {
    useRightPanelStore.getState().setOpen(true);
    expect(localStorage.getItem('right-panel-open')).toBe('1');
    expect(useRightPanelStore.getState().open).toBe(true);
  });

  it('setTab 写 right-panel-tab 并回读', () => {
    useRightPanelStore.getState().setTab('artifacts');
    expect(localStorage.getItem('right-panel-tab')).toBe('artifacts');
    expect(useRightPanelStore.getState().tab).toBe('artifacts');
  });

  it('toggle 翻转开合', () => {
    useRightPanelStore.getState().toggle();
    expect(useRightPanelStore.getState().open).toBe(true);
    useRightPanelStore.getState().toggle();
    expect(useRightPanelStore.getState().open).toBe(false);
  });
});

describe('rightPanelStore — selectArtifact（内联卡片入口）', () => {
  it('开面板 + 切产物 Tab + 记录选中', () => {
    useRightPanelStore.getState().selectArtifact('art-1');
    const s = useRightPanelStore.getState();
    expect(s.open).toBe(true);
    expect(s.tab).toBe('artifacts');
    expect(s.selectedArtifactId).toBe('art-1');
  });

  it('clearSelectedArtifact 只清选中不动开合', () => {
    useRightPanelStore.getState().selectArtifact('art-1');
    useRightPanelStore.getState().clearSelectedArtifact();
    const s = useRightPanelStore.getState();
    expect(s.selectedArtifactId).toBeNull();
    expect(s.open).toBe(true);
    expect(s.tab).toBe('artifacts');
  });
});

describe('rightPanelStore — 未读基线', () => {
  it('markArtifactsSeen 以事件计数为基线', () => {
    useArtifactEventsStore.getState().bump(SID);
    useArtifactEventsStore.getState().bump(SID);
    useRightPanelStore.getState().markArtifactsSeen(SID);
    expect(useRightPanelStore.getState().seenArtifactCount[SID]).toBe(2);
  });
});

describe('maybeAutoOpenArtifactPanel — 自动唤起守卫', () => {
  it('当前会话 + 面板关 + 开关开 → 展开并落产物 Tab', () => {
    maybeAutoOpenArtifactPanel(SID);
    const s = useRightPanelStore.getState();
    expect(s.open).toBe(true);
    expect(s.tab).toBe('artifacts');
  });

  it('面板已开 → 不动（不打断浏览）', () => {
    useRightPanelStore.setState({ open: true, tab: 'changes' });
    maybeAutoOpenArtifactPanel(SID);
    const s = useRightPanelStore.getState();
    expect(s.tab).toBe('changes');
  });

  it('后台会话 → 不展开（只走侧栏徽标）', () => {
    useStore.setState({ currentSessionId: 'sess-other' });
    maybeAutoOpenArtifactPanel(SID);
    expect(useRightPanelStore.getState().open).toBe(false);
  });

  it('Bell 关闭 → 不展开', () => {
    setArtifactAutoOpenEnabled(false);
    expect(isArtifactAutoOpenEnabled()).toBe(false);
    maybeAutoOpenArtifactPanel(SID);
    expect(useRightPanelStore.getState().open).toBe(false);
  });
});
