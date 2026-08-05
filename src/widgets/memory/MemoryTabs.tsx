/**
 * MemoryTabs - 记忆管理页顶部分页（所有记忆 / 用户档案 / 会话摘要）。
 *
 * Gap E (Task 5)：纯受控组件，active + onChange 由 Memory page 持有。
 */
export type MemoryTab = 'all' | 'profile' | 'summary';

const TABS: { key: MemoryTab; label: string }[] = [
  { key: 'all', label: '所有记忆' },
  { key: 'profile', label: '用户档案' },
  { key: 'summary', label: '会话摘要' },
];

export function MemoryTabs({
  active,
  onChange,
}: {
  active: MemoryTab;
  onChange: (tab: MemoryTab) => void;
}) {
  return (
    <div className="flex border-b mb-4" role="tablist" aria-label="记忆视图切换">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={active === tab.key}
          onClick={() => onChange(tab.key)}
          className={`px-4 py-2 text-sm transition-colors ${
            active === tab.key
              ? 'border-b-2 border-blue-500 font-medium text-text'
              : 'text-gray-500 hover:text-text'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
