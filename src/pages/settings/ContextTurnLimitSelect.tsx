/**
 * Context Isolation (Task 8): 上下文轮数限制设置组件。
 *
 * 绑定后端 preferences KV `context_turn_limit`：
 * - null / 空 → 不限（发送全部历史）
 * - 正整数 N → 只发送最近 N 轮（1 轮 = 1 次用户输入 + 1 次助手回复）
 *
 * UI：下拉选择器，选项 null/3/5/8/10/15/20。
 * 放置位置：GeneralTab → "对话" section。
 */
import { useEffect, useState } from 'react';

import { settingsClient } from '../../shared/api/settingsClient';

import { SettingRow } from './components';

const OPTIONS: { label: string; value: number | null }[] = [
  { label: '无限制', value: null },
  { label: '3 轮', value: 3 },
  { label: '5 轮', value: 5 },
  { label: '8 轮', value: 8 },
  { label: '10 轮', value: 10 },
  { label: '15 轮', value: 15 },
  { label: '20 轮', value: 20 },
];

export function ContextTurnLimitSelect(): JSX.Element {
  const [val, setVal] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let mounted = true;
    settingsClient
      .getContextTurnLimit()
      .then((v) => {
        if (mounted) setVal(v);
      })
      .finally(() => {
        if (mounted) setLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleChange = (raw: string): void => {
    const next = raw === 'null' ? null : Number(raw);
    setVal(next);
    void settingsClient.setContextTurnLimit(next);
  };

  return (
    <SettingRow
      label="上下文轮数限制"
      desc="限制每次发送给模型的最近对话轮数（1 轮 = 1 次用户输入 + 1 次助手回复）。无限制 = 发送全部历史"
    >
      <select
        data-testid="settings-context-turn-limit-select"
        aria-label="上下文轮数限制"
        disabled={!loaded}
        value={val === null ? 'null' : String(val)}
        onChange={(e) => handleChange(e.target.value)}
        className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
      >
        {OPTIONS.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>
            {o.label}
          </option>
        ))}
      </select>
    </SettingRow>
  );
}
