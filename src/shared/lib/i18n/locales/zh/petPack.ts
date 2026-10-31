/**
 * 桌宠动画包与多宠物设置文案。
 *
 * 从 chatAndSider.ts 拆出：该聚合词典已接近 800 行架构门禁，新增键放这里
 * 可保持域内聚且不再推高行数。聚合入口见 ../../zh.ts。
 */
export const zhPetPack = {
  'settings.pet.pets': '宠物',
  'settings.pet.pets_desc': '最多 3 只；每只可单独选择动画包和大小，位置互相独立。',
  'settings.pet.pet_label': '宠物',
  'settings.pet.add_pet': '添加宠物',
  'settings.pet.remove_pet': '移除',
  'settings.pet.pets_max': '最多 3 只宠物',
<<<<<<< HEAD
=======
  'settings.pet.external_api': '本地只读状态 API',
  'settings.pet.external_api_desc':
    '开启后仅在 127.0.0.1 的随机端口提供 GET /v1/health 与 /v1/status；请求需携带 Bearer token，端口与令牌写入用户数据目录的 pet-api.json。仅读取状态，不能控制 Sage。',
  'settings.pet.external_api_port': '端口 {port}',
  'settings.pet.external_api_starting': '启动中…',
  'settings.pet.external_api_failed': '启动失败',
>>>>>>> origin/main
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
