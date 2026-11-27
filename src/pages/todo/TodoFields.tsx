/**
 * TodoFields — 待办字段块（新建表单与行内详情面板共用）。
 *
 * 抽出这块的目的是「建的时候能填的字段，事后也必须能改」——两处渲染同一
 * 套控件，字段集合不会各自漂移。
 *
 * 字段值用「本地草稿」表示：``dueAtLocal`` 是 ``datetime-local`` 输入框
 * 的本地字符串，提交时才经 ``toIsoString`` 转成 ISO；``tagsText`` 是逗号
 * /空白分隔的原始文本，提交时才切成标签数组。
 */
import { Bell, Calendar, Flag, Tag } from 'lucide-react';

import type { TodoPriority } from '../../shared/api/types';

/** 可提交（失焦即落库）的字段名。 */
export type TodoFieldsField = 'description' | 'dueAtLocal' | 'projectTag' | 'tagsText';

export interface TodoFieldsValue {
  /** 详细描述（多行）。 */
  description: string;
  priority: TodoPriority;
  /** ``datetime-local`` 的本地值，形如 ``2026-11-27T09:30``。 */
  dueAtLocal: string;
  projectTag: string;
  /** 逗号/空白分隔的标签原始文本。 */
  tagsText: string;
  /** 自定义提醒档位（分钟）。 */
  reminderOffsets: number[];
  specialistId: string;
}

export const EMPTY_TODO_FIELDS: TodoFieldsValue = {
  description: '',
  priority: 'medium',
  dueAtLocal: '',
  projectTag: '',
  tagsText: '',
  reminderOffsets: [],
  specialistId: '',
};

export const PRIORITY_CONFIG: Array<{
  value: TodoPriority;
  label: string;
  color: string;
  icon: string;
}> = [
  { value: 'low', label: '低', color: 'text-green-600', icon: '🟢' },
  { value: 'medium', label: '中', color: 'text-yellow-600', icon: '🟡' },
  { value: 'high', label: '高', color: 'text-red-600', icon: '🔴' },
];

/** 自定义提醒档位预设（分钟）。可多选。 */
export const REMINDER_PRESETS: Array<{ minutes: number; label: string }> = [
  { minutes: 1440, label: '提前1天' },
  { minutes: 60, label: '提前1小时' },
  { minutes: 10, label: '提前10分钟' },
];

/** 后端 ``todo_tags`` 的清洗上限（保持客户端与服务端口径一致）。 */
export const MAX_TAGS = 10;
export const MAX_TAG_LENGTH = 32;

/**
 * 逗号/空白分隔的标签文本 → 标签数组。
 *
 * 清洗规则与后端 ``todo_tags.normalize_tags`` 同口径（去引号/反斜杠/LIKE
 * 通配符、截断长度与数量）——口径不一致会让「看着没改」的失焦也触发一次
 * 无意义的写库。
 */
export function parseTagsText(text: string): string[] {
  const cleaned: string[] = [];
  const seen = new Set<string>();
  for (const raw of text.split(/[,，\s]+/)) {
    let tag = raw.trim();
    for (const ch of ['"', '\\', '%', '_']) tag = tag.replace(ch, '');
    tag = tag.slice(0, MAX_TAG_LENGTH).trim();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    cleaned.push(tag);
    if (cleaned.length >= MAX_TAGS) break;
  }
  return cleaned;
}

interface TodoFieldsProps {
  value: TodoFieldsValue;
  onChange: (next: TodoFieldsValue) => void;
  /** 阶段 3：可选专家列表；空/未提供时不显示负责人选择器。 */
  specialists?: Array<{ id: string; name: string }>;
  /**
   * 字段落库时机回调。详情面板用它区分「立即提交」（优先级 / 提醒 / 负责人）
   * 与「失焦提交」（描述 / 截止日期 / 项目标签 / 标签）；新建表单不需要
   * （提交随整张表单一起走），故为可选。
   */
  onFieldCommit?: (field: TodoFieldsField) => void;
  /**
   * testid 前缀。新建表单传空串（保持既有 ``todo-reminder-60`` 等 id 不
   * 变），详情面板传 ``detail-`` 以免两个面板同时展开时 id 撞车。
   */
  testIdPrefix?: string;
}

export function TodoFields({
  value,
  onChange,
  specialists = [],
  onFieldCommit,
  testIdPrefix = '',
}: TodoFieldsProps) {
  const toggleReminderOffset = (minutes: number) => {
    onChange({
      ...value,
      reminderOffsets: value.reminderOffsets.includes(minutes)
        ? value.reminderOffsets.filter((v) => v !== minutes)
        : [...value.reminderOffsets, minutes],
    });
  };

  const handleDescriptionKeyDown = (e: React.KeyboardEvent) => {
    // Ctrl/Cmd+Enter 提交；普通 Enter 保留换行。
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      onFieldCommit?.('description');
    }
  };

  return (
    <div className="space-y-2.5">
      {/* 描述 */}
      <div>
        <label className="block text-ui-xs text-text-muted mb-1">描述</label>
        <textarea
          value={value.description}
          onChange={(e) => onChange({ ...value, description: e.target.value })}
          onBlur={() => onFieldCommit?.('description')}
          onKeyDown={handleDescriptionKeyDown}
          placeholder="添加详细描述..."
          rows={2}
          data-testid={`${testIdPrefix}todo-description`}
          className="w-full px-2.5 py-1.5 text-xs border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary resize-none placeholder:text-text-muted"
        />
      </div>

      {/* 优先级 */}
      <div>
        <label className="flex items-center gap-1 text-ui-xs text-text-muted mb-1">
          <Flag className="w-3 h-3" />
          优先级
        </label>
        <div className="flex gap-1.5">
          {PRIORITY_CONFIG.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => onChange({ ...value, priority: p.value })}
              className={`flex items-center gap-1 px-2 py-1 text-xs rounded-radius-sm border transition-colors ${
                value.priority === p.value
                  ? `border-primary bg-primary/10 ${p.color}`
                  : 'border-border text-text-muted hover:border-primary/50'
              }`}
              aria-pressed={value.priority === p.value}
              data-testid={`${testIdPrefix}todo-priority-${p.value}`}
            >
              <span>{p.icon}</span>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-3">
        {/* 截止日期 */}
        <div className="flex-1">
          <label className="flex items-center gap-1 text-ui-xs text-text-muted mb-1">
            <Calendar className="w-3 h-3" />
            截止日期
          </label>
          <input
            type="datetime-local"
            value={value.dueAtLocal}
            onChange={(e) => onChange({ ...value, dueAtLocal: e.target.value })}
            onBlur={() => onFieldCommit?.('dueAtLocal')}
            data-testid={`${testIdPrefix}todo-due-at`}
            className="w-full px-2 py-1.5 text-xs border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary"
          />
        </div>

        {/* 项目标签 */}
        <div className="flex-1">
          <label className="flex items-center gap-1 text-ui-xs text-text-muted mb-1">
            <Tag className="w-3 h-3" />
            项目标签
          </label>
          <input
            type="text"
            value={value.projectTag}
            onChange={(e) => onChange({ ...value, projectTag: e.target.value })}
            onBlur={() => onFieldCommit?.('projectTag')}
            placeholder="关联项目..."
            data-testid={`${testIdPrefix}todo-project-tag`}
            className="w-full px-2.5 py-1.5 text-xs border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary placeholder:text-text-muted"
          />
        </div>
      </div>

      {/* 标签 */}
      <div>
        <label className="flex items-center gap-1 text-ui-xs text-text-muted mb-1">
          <Tag className="w-3 h-3" />
          标签
        </label>
        <input
          type="text"
          value={value.tagsText}
          onChange={(e) => onChange({ ...value, tagsText: e.target.value })}
          onBlur={() => onFieldCommit?.('tagsText')}
          placeholder="逗号或空格分隔，如：工作 论文"
          data-testid={`${testIdPrefix}todo-tags`}
          className="w-full px-2.5 py-1.5 text-xs border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary placeholder:text-text-muted"
        />
      </div>

      {/* 提醒档位 */}
      <div>
        <label className="flex items-center gap-1 text-ui-xs text-text-muted mb-1">
          <Bell className="w-3 h-3" />
          提醒（可多选）
        </label>
        <div className="flex flex-wrap gap-1.5">
          {REMINDER_PRESETS.map((preset) => {
            const active = value.reminderOffsets.includes(preset.minutes);
            return (
              <button
                key={preset.minutes}
                type="button"
                onClick={() => toggleReminderOffset(preset.minutes)}
                aria-pressed={active}
                data-testid={`${testIdPrefix}todo-reminder-${preset.minutes}`}
                className={`px-2 py-1 text-xs rounded-radius-sm border transition-colors ${
                  active
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border text-text-muted hover:border-primary/50'
                }`}
              >
                {preset.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* 负责人（阶段 3，仅有专家时显示） */}
      {specialists.length > 0 && (
        <div>
          <label className="flex items-center gap-1 text-ui-xs text-text-muted mb-1">负责人</label>
          <select
            value={value.specialistId}
            onChange={(e) => onChange({ ...value, specialistId: e.target.value })}
            aria-label="负责人"
            data-testid={`${testIdPrefix}todo-specialist`}
            className="w-full px-2 py-1.5 text-xs border border-border rounded-radius-sm bg-background focus:outline-none focus:border-primary"
          >
            <option value="">全局待办（不限负责人）</option>
            {specialists.map((specialist) => (
              <option key={specialist.id} value={specialist.id}>
                {specialist.name}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
