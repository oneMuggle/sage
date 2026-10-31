/**
 * 桌宠动画包设置文案。
 *
 * 从 chatAndSider.ts 拆出：该聚合词典已接近 800 行架构门禁，新增键放这里
 * 可保持域内聚且不再推高行数。聚合入口见 ../../zh.ts。
 */
export const zhPetPack = {
  'settings.pet.pack': '动画包',
  'settings.pet.pack_desc':
    '内置大肥鱼，或导入 zip 格式的自定义动画包（仅支持 webm/mp4/webp/png 等素材，不执行包内脚本）。',
  'settings.pet.pack_builtin': '大肥鱼（内置）',
  'settings.pet.pack_missing': '已缺失',
  'settings.pet.pack_actions': '动画包管理',
  'settings.pet.pack_builtin_desc': '内置素材来自 dsh-pet（MIT）。导入自定义动画包后会自动切换。',
  'settings.pet.pack_import': '导入动画包…',
  'settings.pet.pack_import_busy': '导入中…',
  'settings.pet.pack_export': '导出',
  'settings.pet.pack_delete': '删除',
  'settings.pet.pack_delete_confirm': '确认删除？',
  'settings.pet.pack_imported': '已导入并切换：',
  'settings.pet.pack_exported': '已导出：',
  'settings.pet.pack_deleted': '已删除动画包',
  'settings.pet.pack_failed': '操作失败',
} as const;
