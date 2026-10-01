// src/features/attention/attentionCenter.ts
//
// UX-IA R3 批次 D（数据层）：统一注意力聚合。
//
// 问题：待办信号散落在各面板各算各的 —— 侧栏「对话」入口的 AttnBadge 只数审批 +
// 提问（Sidebar.tsx 的 attentionCount），右栏另算未读产物（rightPanelStore 的
// seenArtifactCount），待办/变更又是各自列表里的数字。用户没有一处能看到
// "现在总共有多少件事等我处理"，折叠侧栏时更是全部消失。
//
// 本文件是**纯函数**：把各来源的计数聚合成一个按风险排序的快照。
// 展示层（rail 角标 + 汇总气泡）由批次 B/D 的 UI 批次接入，届时所有提醒
// 只从这一处取数，不再各自 if。
//
// 刻意**不包含**定时任务：现有 scheduled store 没有 `isDue` 之类的到期判定
// （只有 name/schedule/enabled），"已启用的定时任务数"不等于"需要你处理"。
// 与其发明一个语义不对的信号，不如留空 —— 到期判定应作为独立能力补齐后再登记。

/** 注意力来源。顺序即风险优先级，聚合时按此排序。 */
export const ATTENTION_KINDS = ['approval', 'question', 'artifact', 'todo', 'git'] as const;

type AttentionKind = (typeof ATTENTION_KINDS)[number];

/** 各来源的原始计数（缺省 0 / 负数视为 0）。 */
export interface AttentionInput {
  /** 挂起的工具审批（后端单 agent 循环，至多 1 项） */
  pendingApprovals?: number;
  /** 挂起的向用户提问（同上，至多 1 项） */
  pendingQuestions?: number;
  /** 本次运行内尚未被用户看到的产物数 */
  unseenArtifacts?: number;
  /** 待办清单中 pending / in_progress 的条数 */
  pendingTodos?: number;
  /** 工作区未提交改动涉及的文件数 */
  dirtyFiles?: number;
}

interface AttentionEntry {
  kind: AttentionKind;
  count: number;
  /** 中文短标签，供汇总气泡逐条展示 */
  label: string;
}

export interface AttentionSnapshot {
  /** 所有来源计数之和 */
  total: number;
  /** 仅含 count > 0 的条目，按 ATTENTION_KINDS 的风险顺序排列 */
  entries: AttentionEntry[];
}

const KIND_LABELS: Record<AttentionKind, string> = {
  approval: '待审批',
  question: '待回答',
  artifact: '新产物',
  todo: '待办',
  git: '未提交改动',
};

function sanitize(value: number | undefined): number {
  if (value == null || !Number.isFinite(value) || value <= 0) return 0;
  return Math.floor(value);
}

export function emptyAttentionSnapshot(): AttentionSnapshot {
  return { total: 0, entries: [] };
}

/** 聚合成单一快照。纯函数，无 store 依赖，便于直接单测。 */
export function aggregateAttention(input: AttentionInput): AttentionSnapshot {
  const counts: Record<AttentionKind, number> = {
    approval: sanitize(input.pendingApprovals),
    question: sanitize(input.pendingQuestions),
    artifact: sanitize(input.unseenArtifacts),
    todo: sanitize(input.pendingTodos),
    git: sanitize(input.dirtyFiles),
  };

  const entries = ATTENTION_KINDS.filter((kind) => counts[kind] > 0).map((kind) => ({
    kind,
    count: counts[kind],
    label: KIND_LABELS[kind],
  }));

  return {
    total: entries.reduce((sum, e) => sum + e.count, 0),
    entries,
  };
}

/** 与 `AttnBadge` 的 title 口径一致（shared/ui/AttnBadge.tsx 默认文案）。 */
export function attentionTitle(snapshot: AttentionSnapshot): string {
  if (snapshot.total <= 0) return '无待处理';
  return `${snapshot.total} 项待处理`;
}

/** 汇总气泡的一行摘要，如「待审批 1 · 待办 3」。 */
export function attentionSummary(snapshot: AttentionSnapshot): string {
  if (snapshot.entries.length === 0) return '无待处理';
  return snapshot.entries.map((e) => `${e.label} ${e.count}`).join(' · ');
}
