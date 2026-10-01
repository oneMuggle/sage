/**
 * MemorySettingsTab —— 合并后的「记忆」设置 tab（P1-5 入口收敛）。
 *
 * 为什么要合并：IA1 指出记忆能力散在 4 处（`/memory` 页 + 侧栏 + 设置「记忆」
 * tab + 设置「记忆与知识」tab），IA2 指出术语不统一。实地核实后问题比预想更
 * 具体 —— 「记忆与知识」这个 tab 里**根本没有知识库设置**，它装的是记忆开关 /
 * 清除 / 快照 / 花费限额，而另一个「记忆」tab 装的是嵌入 / 固化 / 备份。
 * 两个都叫「记忆」记忆的 tab，其中一个还名不副实，用户根本无从判断该去哪。
 *
 * 收敛后的形态：
 * 1. 设置页只有一个「记忆」tab —— 不再让用户在两个近义 tab 之间猜。
 * 2. tab 顶部给出**唯一记忆工作台**（`/memory`）的入口。设置页负责「怎么配」，
 *    记忆的浏览 / 删除 / 导出归 `/memory` 页，两边职责不再重叠（IA1）。
 * 3. 术语统一：UI 一律叫「知识库」；`/wiki` 只是后端 API 前缀（wiki_routes），
 *    是跨前后端的既有契约，不在本次 UI 收敛范围内，也不该动。
 *
 * 两个子组件的内部结构保持原样，只调整拼接顺序与重复的小节标题。
 */

import { Link } from 'react-router-dom';

import { MemoryKnowledgeTab } from './MemoryKnowledgeTab';
import { MemoryTab } from './MemoryTab';

export function MemorySettingsTab() {
  return (
    <div className="space-y-8">
      {/* IA1 收敛点：设置页不再自成第三个记忆入口，明确指到唯一工作台。 */}
      <div
        data-testid="memory-workspace-pointer"
        className="flex flex-wrap items-center gap-2 rounded-radius-sm border border-border bg-bg-subtle px-3 py-2"
      >
        <span className="text-xs text-text-secondary">
          这里配置记忆的<strong className="font-medium text-text">行为与引擎</strong>；
          已记住的内容请到记忆页面浏览、删除和导出。
        </span>
        <Link
          to="/memory"
          data-testid="memory-workspace-link"
          className="ml-auto shrink-0 rounded-radius-sm border border-primary px-2 py-1 text-xs text-primary hover:bg-primary/10"
        >
          打开记忆页面
        </Link>
      </div>

      {/* 日常行为：开关 / 清除 / 安全网 / 用量控制 */}
      <MemoryKnowledgeTab />

      {/* 引擎与数据：语义嵌入 / 固化 / 存储位置 / 数据安全 */}
      <div className="border-t border-border pt-6">
        <MemoryTab />
      </div>
    </div>
  );
}
