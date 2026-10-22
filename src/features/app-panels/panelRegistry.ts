// src/features/app-panels/panelRegistry.ts
//
// UX-IA R3 批次 A：侧边槽位注册表。
//
// 立项背景（docs/plans/2026-10-01_ux-ia-round3-panel-slot.md §1.2）：右栏此前
// 存在 chat / wiki / ModelCatalog / TaskCenter 四套并存实现，各自持有 store 与
// localStorage 键，状态散成 ~9 个键，互斥关系只能靠各组件的 useEffect 临时协调
// （"开终端不收右栏"、"右栏最大化后 z-40 浮层仍盖在上面"都是这类漏网的产物）。
//
// 本文件把"有哪些侧边面、各自占哪个槽位、槽位是否互斥、尺寸边界"变成**数据**。
// 组件不再各自 if，改为查表；新增面板必须先在此登记。
//
// 本批次只落地数据层与查询 API，**不迁移任何现有面板** —— 右栏两个核心文件
// （RightPanel.tsx / rightPanelStore.ts）正被 PR #1828 占用，按 AGENTS.md 原则 2
// 不得并发编辑。迁移排期见每项的 migrationBatch。

/** 槽位 = 屏幕上的一个布局位置。同槽位互斥的面必须共用一个槽位。 */
export type PanelSlot = 'left-rail' | 'left-list' | 'right' | 'bottom' | 'floating';

export interface SlotGeometry {
  /** 同槽位是否互斥（同一时刻只能有一个面板处于激活/打开态）。 */
  exclusive: boolean;
  /** 尺寸轴：x = 宽度，y = 高度。 */
  axis: 'x' | 'y';
  minSize: number;
  maxSize: number;
  defaultSize: number;
  /** 是否允许最大化（铺满主内容区）。 */
  maximizable: boolean;
}

/**
 * 各槽位的几何与互斥契约。
 * 尺寸边界取自现状（useResizablePanel / useResizableSidebar 的 min/max/default），
 * 迁移后行为对用户不变。
 */
export const PANEL_SLOTS: Readonly<Record<PanelSlot, SlotGeometry>> = {
  // 56px 图标 rail（Sidebar collapsed 态）
  'left-rail': {
    exclusive: true,
    axis: 'x',
    minSize: 48,
    maxSize: 72,
    defaultSize: 56,
    maximizable: false,
  },
  // 240px 内容列：批次 B 落地后，同一时刻只渲染一个列表
  'left-list': {
    exclusive: true,
    axis: 'x',
    minSize: 200,
    maxSize: 420,
    defaultSize: 240,
    maximizable: false,
  },
  // 右栏：chat / wiki / ModelCatalog 三套实现迁入后单占（RightPanel.tsx:72-76 的 280~600）
  right: {
    exclusive: true,
    axis: 'x',
    minSize: 280,
    maxSize: 600,
    defaultSize: 320,
    maximizable: true,
  },
  // 底部终端（terminalPanelStore.ts:16-18 的 120~600）
  bottom: {
    exclusive: true,
    axis: 'y',
    minSize: 120,
    maxSize: 600,
    defaultSize: 240,
    maximizable: true,
  },
  // 浮层（TaskCenterWidget 当前的 fixed bottom-4 right-4 z-40 一类）。
  // 不互斥：允许与任何槽位并存，但**必须**让位于其它槽位的最大化态（见 store）。
  floating: {
    exclusive: false,
    axis: 'x',
    minSize: 0,
    maxSize: 0,
    defaultSize: 0,
    maximizable: false,
  },
};

export const PANEL_SLOT_IDS = Object.keys(PANEL_SLOTS) as PanelSlot[];

/**
 * 迁移批次：本登记项接入统一槽位的时间点。
 * A = 数据层已就绪（无 UI 改动）；B/C/D = 对应批次的迁移目标。
 */
export type PanelMigrationBatch = 'A' | 'B' | 'C' | 'D';

export interface PanelDefinition {
  id: string;
  slot: PanelSlot;
  label: string;
  migrationBatch: PanelMigrationBatch;
  /** 现状落点（迁移前的真实位置），便于迁移时逐项核对。 */
  currentOwner?: string;
}

export const PANEL_DEFINITIONS: readonly PanelDefinition[] = [
  // ── 左栏（批次 B：rail + 单列表内容列） ──
  {
    id: 'sider-rail',
    slot: 'left-rail',
    label: '侧栏图标栏',
    migrationBatch: 'B',
    currentOwner: 'widgets/layout/Sidebar.tsx:296-364',
  },
  {
    id: 'sider-projects',
    slot: 'left-list',
    label: '项目',
    migrationBatch: 'B',
    currentOwner: 'widgets/sidebar/sections/SidebarProjectList.tsx',
  },
  {
    id: 'sider-conversations',
    slot: 'left-list',
    label: '会话',
    migrationBatch: 'B',
    currentOwner: 'widgets/sidebar/sections/ConversationsSection.tsx',
  },
  {
    id: 'sider-git',
    slot: 'left-list',
    label: 'Git 状态',
    migrationBatch: 'B',
    currentOwner: 'widgets/sidebar/sections/GitStatusSection.tsx',
  },
  // ── 右栏（批次 C，等 PR #1828 合并） ──
  {
    id: 'chat-inspector',
    slot: 'right',
    label: '对话检查器',
    migrationBatch: 'C',
    currentOwner: 'widgets/chat/RightPanel.tsx',
  },
  {
    id: 'wiki-inspector',
    slot: 'right',
    label: '知识库检查器',
    migrationBatch: 'C',
    currentOwner: 'widgets/wiki/RightPanel.tsx',
  },
  {
    id: 'model-catalog-detail',
    slot: 'right',
    label: '模型目录详情',
    migrationBatch: 'C',
    currentOwner: 'pages/ModelCatalog.tsx（w-96 / w-[480px] 内联栏）',
  },
  {
    id: 'terminal',
    slot: 'bottom',
    label: '终端',
    migrationBatch: 'C',
    currentOwner: 'widgets/chat/TerminalPanel.tsx + features/terminal-panel',
  },
  // ── 浮层（批次 C：收进注册表，不再以 z-40 压右栏） ──
  {
    id: 'task-center',
    slot: 'floating',
    label: '任务中心',
    migrationBatch: 'C',
    currentOwner: 'widgets/task-center/TaskCenterWidget.tsx:305',
  },
];

export function getPanelDefinition(id: string): PanelDefinition | undefined {
  return PANEL_DEFINITIONS.find((p) => p.id === id);
}

export function isRegisteredPanel(id: string): boolean {
  return getPanelDefinition(id) !== undefined;
}

export function panelsForSlot(slot: PanelSlot): readonly PanelDefinition[] {
  return PANEL_DEFINITIONS.filter((p) => p.slot === slot);
}

export function slotGeometry(slot: PanelSlot): SlotGeometry {
  return PANEL_SLOTS[slot];
}

/** 尺寸夹取到槽位边界。非有限值（NaN / 越界脏数据）回落默认值。 */
export function clampSize(slot: PanelSlot, size: number): number {
  const { minSize, maxSize, defaultSize } = PANEL_SLOTS[slot];
  if (!Number.isFinite(size)) return defaultSize;
  return Math.min(maxSize, Math.max(minSize, Math.round(size)));
}

/** 槽位互斥：返回 true 表示两个面板不能同时占用各自槽位。 */
export function isExclusiveConflict(aId: string, bId: string): boolean {
  const a = getPanelDefinition(aId);
  const b = getPanelDefinition(bId);
  if (!a || !b) return false;
  return a.slot === b.slot && PANEL_SLOTS[a.slot].exclusive;
}

export interface PanelRegistryAuditSnapshot {
  slotCount: number;
  exclusiveSlotCount: number;
  maximizableSlotCount: number;
  panelCount: number;
  batchCountMap: Record<PanelMigrationBatch, number>;
  slotIds: PanelSlot[];
  panelIds: string[];
  signature: string;
}

export function buildPanelRegistryAuditSnapshot(
  definitions: readonly PanelDefinition[] = PANEL_DEFINITIONS,
): PanelRegistryAuditSnapshot {
  const safeDefs: readonly PanelDefinition[] = Array.isArray(definitions) ? definitions : PANEL_DEFINITIONS;
  const slotIds = [...PANEL_SLOT_IDS];
  const slotCount = slotIds.length;
  const exclusiveSlotCount = slotIds.filter((s) => PANEL_SLOTS[s].exclusive).length;
  const maximizableSlotCount = slotIds.filter((s) => PANEL_SLOTS[s].maximizable).length;
  const batchCountMap: Record<PanelMigrationBatch, number> = { A: 0, B: 0, C: 0, D: 0 };
  for (const def of safeDefs) {
    if (def.migrationBatch in batchCountMap) {
      batchCountMap[def.migrationBatch] += 1;
    }
  }
  const panelIds = safeDefs.map((d) => d.id);
  const panelCount = panelIds.length;
  const signature = `${slotCount}|${exclusiveSlotCount}|${maximizableSlotCount}|${panelCount}|${batchCountMap.A},${batchCountMap.B},${batchCountMap.C},${batchCountMap.D}`;
  return {
    slotCount,
    exclusiveSlotCount,
    maximizableSlotCount,
    panelCount,
    batchCountMap,
    slotIds,
    panelIds,
    signature,
  };
}

export function buildPanelRegistryAuditJson(
  definitions: readonly PanelDefinition[] = PANEL_DEFINITIONS,
): string {
  return JSON.stringify(buildPanelRegistryAuditSnapshot(definitions), null, 2);
}

export function auditPanelRegistryGovernance(
  state: {
    slotCount?: number;
    panelCount?: number;
  } = {},
): {
  module: 'src/features/app-panels/panelRegistry.ts';
  phase: 'P157';
  slotCount: number;
  panelCount: number;
  healthy: boolean;
} {
  const slotCount =
    typeof state.slotCount === 'number' && Number.isFinite(state.slotCount)
      ? Math.max(0, Math.trunc(state.slotCount))
      : PANEL_SLOT_IDS.length;
  const panelCount =
    typeof state.panelCount === 'number' && Number.isFinite(state.panelCount)
      ? Math.max(0, Math.trunc(state.panelCount))
      : PANEL_DEFINITIONS.length;
  return {
    module: 'src/features/app-panels/panelRegistry.ts',
    phase: 'P157',
    slotCount,
    panelCount,
    healthy: slotCount >= 1 && panelCount >= 1,
  };
}
