const zh = {
  saving: '正在确认保存…',
  saved: '已确认保存',
  saveFailed: '保存未确认，请检查后端连接后重试。实际状态以服务端为准。',
  retry: '重新读取',
  modelRequired: '请选择或填写一个模型 ID 后再保存。',
  memoryUnconfirmed: '无法读取或保存记忆偏好，当前会话保持暂停长期记忆。请修复本机存储后再恢复。',
  awaitingReview: '待验收成果',
  taskSummary: '运行 {running} · 排队/暂停 {other} · 待确认 {awaiting} · 已结束 {finished}',
};
const en: typeof zh = {
  saving: 'Confirming save…',
  saved: 'Save confirmed',
  saveFailed:
    'Save was not confirmed. Check the backend and retry; server state remains authoritative.',
  retry: 'Reload',
  modelRequired: 'Select or enter a model ID before saving.',
  memoryUnconfirmed:
    'Memory preferences could not be read or saved. Long-term memory stays paused for this chat until local storage is repaired.',
  awaitingReview: 'Review delivery',
  taskSummary:
    'Running {running} · Queued/paused {other} · Needs attention {awaiting} · Finished {finished}',
};
export function productMessages(locale?: string): typeof zh {
  return locale === 'en' ? en : zh;
}
