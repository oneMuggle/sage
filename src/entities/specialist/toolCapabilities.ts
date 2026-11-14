/**
 * 专家工具「能力包」映射（前端静态声明）。
 *
 * 每个包把一组后端工具名聚合成用户可理解的能力，供向导勾选与详情页
 * 展示。工具名必须与后端注册表精确一致（`_EXPECTED_ONLINE` 快照），
 * 由 `backend/tests/unit/test_specialist_tool_packs_drift.py` 守卫生锈。
 *
 * `requiresMode` 是该包内工具**免逐次审批**所需的最低权限模式：
 * READ 工具任意模式可用；WRITE 需 `workspace_write`（`prompt` 下逐次
 * 审批）；EXECUTE 或自管理工具需 `full_access`（`prompt` 下逐次审批）。
 * 它只驱动提示与默认值，实际执行仍由后端权限引擎裁决——单一真相源
 * 仍是 `backend/tools/permissions.py`。
 */
import type { AgentProfile } from '../../shared/api';

export type SpecialistPermissionMode = Exclude<AgentProfile['permission_mode'], undefined>;

export interface ToolCapabilityPack {
  id: string;
  label: string;
  description: string;
  tools: readonly string[];
  requiresMode: SpecialistPermissionMode;
}

/** 与后端 `_SPECIALIST_MODE_RANK` 同序；`prompt` 位于 `workspace_write` 之下。 */
export const PERMISSION_MODE_RANK: Record<SpecialistPermissionMode, number> = {
  read_only: 0,
  prompt: 1,
  workspace_write: 2,
  full_access: 3,
};

export const TOOL_CAPABILITY_PACKS: readonly ToolCapabilityPack[] = [
  {
    id: 'file-read',
    label: '文件读取与检索',
    description: '读取文件、列目录、按文件名/内容/符号检索代码库',
    tools: [
      'read_file',
      'list_dir',
      'glob_search',
      'grep_search',
      'codebase_search',
      'symbol_search',
      'file_summary',
    ],
    requiresMode: 'read_only',
  },
  {
    id: 'file-write',
    label: '文件编辑',
    description: '写入/编辑文件与补丁应用',
    tools: ['write_file', 'edit_file', 'apply_patch'],
    requiresMode: 'workspace_write',
  },
  {
    id: 'shell',
    label: '命令与代码执行',
    description: '运行 shell 命令、代码、REPL 与运行时诊断',
    tools: [
      'bash',
      'bash_output',
      'kill_shell',
      'wait_background',
      'runtime_exec',
      'execute_code',
      'repl',
      'runtime_probe',
      'project_diagnose',
    ],
    requiresMode: 'full_access',
  },
  {
    id: 'network',
    label: '网络检索与下载',
    description: '联网搜索、抓取网页与下载文件',
    tools: ['web_search', 'web_fetch', 'http_download', 'download_status', 'download_cancel'],
    requiresMode: 'workspace_write',
  },
  {
    id: 'memory',
    label: '记忆与会话检索',
    description: '检索历史记忆与会话，并写入新的长期记忆',
    tools: ['memory_search', 'session_search', 'memory_save'],
    requiresMode: 'workspace_write',
  },
  {
    id: 'office',
    label: '办公文档',
    description:
      '创建/读取/审校/修复 Word、PDF、PPT、LaTeX 文档（删除类操作为执行面，需在高级白名单单独添加 office_delete）',
    tools: [
      'office_list',
      'office_read',
      'office_create',
      'office_update',
      'office_restore',
      'office_archive',
      'office_read_pdf',
      'office_generate_pdf',
      'office_read_pdf_form',
      'office_fill_pdf_form',
      'office_analyze_word_template',
      'office_fill_word_template',
      'office_analyze_ppt_template',
      'office_fill_ppt_template',
      'office_analyze',
      'office_journal_parse_template',
      'office_journal_fill_from_content',
      'office_journal_generate_article',
      'office_journal_validate',
      'office_parse_bibtex',
      'office_lint_word',
      'office_audit_word',
      'office_fix_word',
      'office_extract_rules',
      'office_revise_word',
      'office_batch_audit',
      'office_render_audit',
      'office_read_latex',
      'office_analyze_latex_template',
      'office_fill_latex_template',
      'office_audit_latex',
      'office_audit_latex_pdf',
      'office_check_latex_compliance',
      'office_compile_latex',
      'office_latexdiff',
      'office_extract_latex_project',
      'office_repair_word',
      'office_refresh_toc',
    ],
    requiresMode: 'workspace_write',
  },
  {
    id: 'git',
    label: 'Git 与检查点',
    description: '查看与变更 Git 状态，创建/恢复工作区检查点',
    tools: [
      'git_branch',
      'git_status',
      'git_diff',
      'git_log',
      'git_commit_message',
      'git_checkout',
      'git_stash',
      'git_commit',
      'checkpoint_create',
      'checkpoint_list',
      'checkpoint_restore',
    ],
    requiresMode: 'workspace_write',
  },
  {
    id: 'browser',
    label: '浏览器自动化',
    description: '启动浏览器、导航、截图与页面交互',
    tools: [
      'browser_launch',
      'browser_navigate',
      'browser_snapshot',
      'browser_interact',
      'browser_screenshot',
      'browser_cookies',
      'browser_downloads',
      'browser_close',
      'browser_login',
    ],
    requiresMode: 'full_access',
  },
  {
    id: 'multimodal',
    label: '多模态',
    description: '语音合成/识别、图像生成与 OCR',
    tools: ['text_to_speech', 'speech_to_text', 'generate_image', 'ocr_image'],
    requiresMode: 'workspace_write',
  },
  {
    id: 'design',
    label: '设计原型',
    description: '列出设计系统/模板并生成、迭代、导出原型',
    tools: [
      'design_list_systems',
      'design_list_templates',
      'design_generate',
      'design_iterate',
      'design_export',
      'design_embed_chart',
    ],
    requiresMode: 'workspace_write',
  },
  {
    id: 'sage-config',
    label: 'Sage 配置与自检',
    description: '读取/修改 Sage 配置，查看运行时状态与诊断',
    tools: [
      'read_sage_config',
      'update_sage_config',
      'diagnose_sage_config',
      'sage_self_status',
      'sage_doctor',
      'sage_usage',
    ],
    requiresMode: 'full_access',
  },
  {
    id: 'schedule',
    label: '定时任务',
    description: '创建/取消定时任务与会话唤醒',
    tools: [
      'schedule_task',
      'list_scheduled_tasks',
      'cancel_scheduled_task',
      'wake_session_at',
      'wake_on_background',
    ],
    requiresMode: 'full_access',
  },
  {
    id: 'skills',
    label: '技能·子代理·待办',
    description: '调用/保存技能，派生子代理，维护会话待办',
    tools: [
      'skill',
      'skill_save',
      'agent',
      'ask_user_question',
      'todo_write',
      'structured_output',
      'add_todo',
      'list_todos',
      'complete_todo',
      'update_todo',
      'delete_todo',
    ],
    requiresMode: 'full_access',
  },
  {
    id: 'plugins',
    label: '插件工具',
    description: '放行全部运行中插件工具（仍逐次审批）',
    tools: ['plugin__*'],
    requiresMode: 'full_access',
  },
];

export type PackSelectionState = 'all' | 'partial' | 'none';

export function findToolCapabilityPack(id: string): ToolCapabilityPack | undefined {
  return TOOL_CAPABILITY_PACKS.find((pack) => pack.id === id);
}

/** 包内工具在当前白名单中的覆盖状态。 */
export function packSelectionState(
  tools: readonly string[],
  pack: ToolCapabilityPack,
): PackSelectionState {
  const selected = pack.tools.filter((tool) => tools.includes(tool)).length;
  if (selected === 0) return 'none';
  return selected === pack.tools.length ? 'all' : 'partial';
}

/** 勾选加入包内缺失工具，取消只移除该包自己的工具名（保留手工条目）。 */
export function togglePackInTools(
  tools: readonly string[],
  pack: ToolCapabilityPack,
  selected: boolean,
): string[] {
  if (selected) {
    const missing = pack.tools.filter((tool) => !tools.includes(tool));
    return missing.length ? [...tools, ...missing] : [...tools];
  }
  return tools.filter((tool) => !pack.tools.includes(tool));
}

export interface ToolSelectionSummary {
  /** 完全覆盖的包。 */
  covered: ToolCapabilityPack[];
  /** 部分覆盖的包。 */
  partial: ToolCapabilityPack[];
  /** 不属于任何能力包的条目（含插件精确名、office_delete 等）。 */
  uncategorized: string[];
}

export function describeToolSelection(tools: readonly string[]): ToolSelectionSummary {
  const covered: ToolCapabilityPack[] = [];
  const partial: ToolCapabilityPack[] = [];
  for (const pack of TOOL_CAPABILITY_PACKS) {
    const state = packSelectionState(tools, pack);
    if (state === 'all') covered.push(pack);
    else if (state === 'partial') partial.push(pack);
  }
  const known = new Set(TOOL_CAPABILITY_PACKS.flatMap((pack) => pack.tools));
  const uncategorized = tools.filter((tool) => !known.has(tool));
  return { covered, partial, uncategorized };
}

/** 一组能力包中要求的最高权限模式；空集合返回 null。 */
export function highestRequiredMode(
  packs: readonly ToolCapabilityPack[],
): SpecialistPermissionMode | null {
  let highest: SpecialistPermissionMode | null = null;
  for (const pack of packs) {
    if (
      highest === null ||
      PERMISSION_MODE_RANK[pack.requiresMode] > PERMISSION_MODE_RANK[highest]
    ) {
      highest = pack.requiresMode;
    }
  }
  return highest;
}

export interface ModeGateWarning {
  level: 'deny' | 'approval';
  message: string;
}

/**
 * 当前权限模式对某个能力包的影响：`null` 表示无额外限制。
 *
 * 只做提示，不禁用选择——实际裁决仍在后端权限引擎。
 */
export function describeModeGate(
  mode: SpecialistPermissionMode,
  pack: ToolCapabilityPack,
): ModeGateWarning | null {
  if (PERMISSION_MODE_RANK[mode] >= PERMISSION_MODE_RANK[pack.requiresMode]) return null;
  if (mode === 'prompt') {
    return {
      level: 'approval',
      message: `当前为「逐次确认」模式，${pack.label}中的写入/执行类工具每次调用都需你确认。`,
    };
  }
  return {
    level: 'deny',
    message: `当前权限模式下，${pack.label}中的写入/执行类工具会被拒绝。`,
  };
}

/** 新建专家的默认能力包：只读、开箱可用。 */
export const DEFAULT_SPECIALIST_PACK_IDS: readonly string[] = ['file-read', 'network', 'memory'];

/** 默认能力包展开后的工具名（去重、保持包顺序）。 */
export function defaultSpecialistTools(): string[] {
  const tools: string[] = [];
  for (const id of DEFAULT_SPECIALIST_PACK_IDS) {
    const pack = findToolCapabilityPack(id);
    if (!pack) continue;
    for (const tool of pack.tools) {
      if (!tools.includes(tool)) tools.push(tool);
    }
  }
  return tools;
}
