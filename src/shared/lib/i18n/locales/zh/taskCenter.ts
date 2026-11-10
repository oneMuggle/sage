// 侧边栏任务中心文案域（2026-11-09）。
// 独立分域 —— chatAndSider.ts 已在架构基线内（825 行），禁止再加键。
export const zhTaskCenter = {
  // 分区
  'taskCenter.section.title': '任务',
  'taskCenter.section.empty': '暂无正在进行的任务',
  'taskCenter.section.more': '还有 {count} 条',

  // 来源
  'taskCenter.source.registry': '页面任务',
  'taskCenter.source.chat': '后台会话',
  'taskCenter.source.lane': '编排',
  'taskCenter.source.goal': '闲时目标',
  'taskCenter.source.todo': '待办',
  'taskCenter.source.scheduled': '定时任务',

  // 分组
  'taskCenter.group.active': '进行中',
  'taskCenter.group.failed': '失败',
  'taskCenter.group.finished': '已完成',

  // 动作
  'taskCenter.action.cancel': '取消任务',
  'taskCenter.action.pause': '暂停',
  'taskCenter.action.resume': '恢复',
  'taskCenter.action.runNow': '立即运行',
  'taskCenter.action.clearFinished': '清除已完成',
  'taskCenter.action.viewDetail': '查看详情',

  // 筛选
  'taskCenter.filter.all': '全部',

  // 页面
  'taskCenter.page.title': '任务中心',
  'taskCenter.page.subtitle': '所有正在运行、等待处理与最近完成的任务',
  'taskCenter.page.empty': '当前没有任务',

  // 角标
  'taskCenter.badge.title': '任务中心（{count} 项需关注）',
} as const;
