/**
 * Settings 页面 - 记忆管理 Tab
 *
 * fix/security-perf-quickwins §1.3b f (2026-08-09):
 * - "同步到内部服务器" 开关从误绑的 `settings.autoMemory` 改为独立的
 *   `settings.memoryServerSync` 字段。`autoMemory` 实际语义是"对话中
 *   自动提取关键信息"（见 GeneralTab §"自动记忆提取"），与本 Tab
 *   的"同步到企业内部服务器"语义不同——同字段双语义是误导。
 * - 移除硬编码的 `%APPDATA%\Sage\memory.db` 展示（与 §1.4 "假功能/
 *   死设置清理" 同源治理）：实际路径由 SAGE_DB_PATH 环境变量决定
 *   （见 backend/data/database.py:158-173），Electron 模式下指向
 *   `%APPDATA%/Sage/sage.db`，dev 模式下指向 `<repo>/data/sage.db`，
 *   写死展示既不准也无用。
 */

import type { EndpointsTabProps } from './components';
import { SettingRow, Toggle } from './components';

export function MemoryTab({ settings, updateSettings }: EndpointsTabProps) {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">记忆管理</h3>
        <SettingRow
          label="本地存储"
          desc="记忆数据存储在本地 SQLite 数据库中，具体路径由 SAGE_DB_PATH 环境变量与运行模式决定"
        >
          <span className="px-2 py-1 text-xs text-text-secondary font-mono">
            本地 SQLite 数据库
          </span>
        </SettingRow>
        <SettingRow
          label="同步到内部服务器"
          desc="联网时将记忆增量同步到企业内部服务器（功能规划中，后端尚未接线）"
        >
          <Toggle
            value={settings.memoryServerSync}
            onChange={(v) => updateSettings({ memoryServerSync: v })}
          />
        </SettingRow>
      </section>
    </div>
  );
}