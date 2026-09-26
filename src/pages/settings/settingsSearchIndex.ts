/**
 * 设置项搜索索引 (R41 升级: 从"只搜 tab 名"到"搜到具体设置项")。
 *
 * 每个条目对应设置页一个可见控件/分组，keywords 为小写搜索词
 * (中英混排，命中时任一子串包含即可)。新增设置项时在此登记一行，
 * 设置页搜索即可发现它。
 */

export type SettingsTabKey =
  | 'general'
  | 'basic'
  | 'memory-knowledge'
  | 'tools-connections'
  | 'endpoints'
  | 'models'
  | 'orchestration'
  | 'memory'
  | 'network'
  | 'mcp'
  | 'remote-workspaces'
  | 'zotero'
  | 'runtime'
  | 'evolution'
  | 'updates'
  | 'providers';

export interface SettingsSearchEntry {
  /** 条目稳定标识 */
  key: string;
  /** 所属 tab */
  tab: SettingsTabKey;
  /** 展示名 (中文，与控件 label 一致) */
  label: string;
  /** 展示名 (英文) */
  labelEn: string;
  /** 小写关键词，含中英别名与 setting key 本身 */
  keywords: string;
}

export const SETTINGS_SEARCH_INDEX: SettingsSearchEntry[] = [
  // ── 通用 ──
  {
    key: 'theme',
    tab: 'basic',
    label: '主题',
    labelEn: 'Theme',
    keywords: 'theme 主题 深色 浅色 dark light 外观',
  },
  {
    key: 'locale',
    tab: 'basic',
    label: '界面语言',
    labelEn: 'Language',
    keywords: 'locale language 语言 中文 english',
  },
  {
    key: 'font_ui',
    tab: 'basic',
    label: '界面字体',
    labelEn: 'UI font',
    keywords: 'font 字体 ui interface 外观',
  },
  {
    key: 'font_size_ui',
    tab: 'basic',
    label: '界面字号',
    labelEn: 'UI font size',
    keywords: 'font size 字号 字体大小',
  },
  {
    key: 'font_code',
    tab: 'basic',
    label: '代码字体',
    labelEn: 'Code font',
    keywords: 'code font 代码字体 等宽 mono',
  },
  {
    key: 'font_size_code',
    tab: 'basic',
    label: '代码字号',
    labelEn: 'Code font size',
    keywords: 'code font size 代码字号',
  },
  {
    key: 'streaming',
    tab: 'basic',
    label: '流式输出',
    labelEn: 'Streaming',
    keywords: 'streaming 流式 逐字 输出',
  },
  {
    key: 'timezone',
    tab: 'basic',
    label: 'IANA 时区',
    labelEn: 'Timezone',
    keywords: 'timezone 时区 iana asia/shanghai',
  },
  {
    key: 'logTimezone',
    tab: 'basic',
    label: '日志时区',
    labelEn: 'Log timezone',
    keywords: 'log timezone 日志时区 utc',
  },
  {
    key: 'autoMemory',
    tab: 'memory-knowledge',
    label: '自动记忆提取',
    labelEn: 'Auto memory extraction',
    keywords: 'automemory 记忆 自动提取',
  },
  {
    key: 'confirmDelete',
    tab: 'memory-knowledge',
    label: '确认后再删除记忆',
    labelEn: 'Confirm before deleting memory',
    keywords: 'confirmdelete 删除记忆 确认',
  },
  {
    key: 'context_turn_limit',
    tab: 'memory-knowledge',
    label: '上下文轮数限制',
    labelEn: 'Context turn limit',
    keywords: 'context turn limit 上下文 轮数 隔离 不限',
  },
  {
    key: 'attachment_rag',
    tab: 'basic',
    label: '超长文档检索注入',
    labelEn: 'Attachment RAG',
    keywords: 'rag 附件 检索 embedding 长文档 top_k',
  },
  {
    key: 'auto_checkpoint',
    tab: 'memory-knowledge',
    label: '发送前自动快照',
    labelEn: 'Auto checkpoint',
    keywords: 'checkpoint 快照 安全网 回滚 撤销',
  },
  {
    key: 'close_to_tray',
    tab: 'basic',
    label: '关闭时隐藏到托盘',
    labelEn: 'Close to tray',
    keywords: 'tray 托盘 关闭 最小化',
  },
  {
    key: 'demoMode',
    tab: 'basic',
    label: '演示模式',
    labelEn: 'Demo mode',
    keywords: 'demo 演示 示例数据 离线',
  },
  {
    key: 'permission_mode',
    tab: 'tools-connections',
    label: '权限模式',
    labelEn: 'Permission mode',
    keywords: 'permission 权限 只读 full_access workspace_write 审批',
  },
  {
    key: 'fallback_model',
    tab: 'tools-connections',
    label: '降级模型 (fallback)',
    labelEn: 'Fallback model',
    keywords: 'fallback 降级模型 限流 重试',
  },
  {
    key: 'hooks',
    tab: 'tools-connections',
    label: '钩子 (Hooks)',
    labelEn: 'Hooks',
    keywords: 'hooks 钩子 pre_tool_use 命令',
  },
  {
    key: 'spend_limit',
    tab: 'basic',
    label: '每日花费限额',
    labelEn: 'Daily spend limit',
    keywords: 'spend limit 花费 限额 usd 预算',
  },
  {
    key: 'usage',
    tab: 'basic',
    label: '用量统计',
    labelEn: 'Usage',
    keywords: 'usage 用量 token 统计 导出',
  },
  {
    key: 'diagnostics',
    tab: 'basic',
    label: '诊断与日志级别',
    labelEn: 'Diagnostics',
    keywords: 'diagnostics 诊断 日志级别 log level',
  },
  {
    key: 'gateway',
    tab: 'tools-connections',
    label: '消息网关 (Telegram/Discord/Slack)',
    labelEn: 'Chat gateways',
    keywords: 'gateway telegram discord slack 网关 绑定',
  },
  {
    key: 'reset',
    tab: 'basic',
    label: '恢复默认设置',
    labelEn: 'Reset settings',
    keywords: 'reset 恢复默认 重置 数据',
  },

  // ── 端点 ──
  {
    key: 'endpoints',
    tab: 'endpoints',
    label: '端点管理',
    labelEn: 'Endpoints',
    keywords: 'endpoint base url api key 端点 协议 模型探测',
  },

  // ── 模型 ──
  {
    key: 'model_selections',
    tab: 'models',
    label: '模型选择',
    labelEn: 'Model selection',
    keywords: 'model chat vision embedding tts asr image 模型选择',
  },
  {
    key: 'max_context',
    tab: 'models',
    label: '最大上下文长度',
    labelEn: 'Max context',
    keywords: 'maxcontext 上下文 context window 长度',
  },
  {
    key: 'auto_context',
    tab: 'models',
    label: '自动推断上下文窗口',
    labelEn: 'Auto context',
    keywords: 'autocontext 上下文 自动推断 catalog',
  },
  {
    key: 'temperature',
    tab: 'models',
    label: 'Temperature',
    labelEn: 'Temperature',
    keywords: 'temperature 温度 随机性 采样',
  },
  {
    key: 'model_catalog',
    tab: 'models',
    label: '模型目录管理',
    labelEn: 'Model catalog',
    keywords: 'catalog 模型目录 管理',
  },

  // ── 编排 ──
  {
    key: 'orch.planPreflightEnabled',
    tab: 'orchestration',
    label: '拆解前澄清需求',
    labelEn: 'Pre-plan clarification',
    keywords: 'orch 编排 澄清 提问 计划前置 planpreflightenabled',
  },
  {
    key: 'orch.planScoutEnabled',
    tab: 'orchestration',
    label: '拆解前事实侦察',
    labelEn: 'Pre-plan scout',
    keywords: 'orch 编排 侦察 事实 计划前置 planscoutenabled',
  },
  {
    key: 'orch.maxConcurrentSubagents',
    tab: 'orchestration',
    label: '最大并发子任务数',
    labelEn: 'Max concurrent subagents',
    keywords: 'orch 编排 并发 子任务 maxconcurrentsubagents',
  },
  {
    key: 'orch.maxRetries',
    tab: 'orchestration',
    label: '子任务重试次数',
    labelEn: 'Subtask retries',
    keywords: 'orch 编排 重试 maxretries',
  },
  {
    key: 'orch.maxLaneIterations',
    tab: 'orchestration',
    label: 'Lane 迭代上限',
    labelEn: 'Lane iterations',
    keywords: 'orch 编排 lane 迭代 maxlaneiterations',
  },
  {
    key: 'orch.maxSubagentIterations',
    tab: 'orchestration',
    label: '子代理迭代上限',
    labelEn: 'Subagent iterations',
    keywords: 'orch 编排 子代理 迭代 maxsubagentiterations',
  },
  {
    key: 'orch.maxAggregateChars',
    tab: 'orchestration',
    label: '聚合结果上限',
    labelEn: 'Max aggregate chars',
    keywords: 'orch 编排 聚合 字符 maxaggregatechars',
  },
  {
    key: 'orch.maxSubagentResultChars',
    tab: 'orchestration',
    label: '单结果截断上限',
    labelEn: 'Max subagent result chars',
    keywords: 'orch 编排 截断 字符 maxsubagentresultchars',
  },
  {
    key: 'orch.runTokenBudget',
    tab: 'orchestration',
    label: 'Run token 预算',
    labelEn: 'Run token budget',
    keywords: 'orch 编排 token 预算 runtokenbudget',
  },
  {
    key: 'orch.runWallClockLimitMinutes',
    tab: 'orchestration',
    label: 'Run 墙钟上限',
    labelEn: 'Run wall-clock limit',
    keywords: 'orch 编排 墙钟 超时 runwallclocklimitminutes',
  },
  {
    key: 'orch.subagentTaskTimeoutS',
    tab: 'orchestration',
    label: '单子任务超时',
    labelEn: 'Subagent task timeout',
    keywords: 'orch 编排 子任务 超时 subagenttasktimeouts',
  },
  {
    key: 'orch.maxRetryOfChains',
    tab: 'orchestration',
    label: '重派链上限',
    labelEn: 'Retry chain limit',
    keywords: 'orch 编排 重派 retry_of maxretryofchains',
  },
  {
    key: 'orch.subagentApprovalMode',
    tab: 'orchestration',
    label: '子代理自动批准',
    labelEn: 'Subagent auto approval',
    keywords: 'orch 编排 审批 自动批准 subagentapprovalmode',
  },
  {
    key: 'orch.worktreeIsolation',
    tab: 'orchestration',
    label: '子任务 git worktree 隔离',
    labelEn: 'Worktree isolation',
    keywords: 'orch 编排 worktree 隔离 git worktreeisolation',
  },
  {
    key: 'orch.scratchRoot',
    tab: 'orchestration',
    label: 'Scratch 根目录名',
    labelEn: 'Scratch root',
    keywords: 'orch 编排 scratch 目录 scratchroot',
  },

  // ── 记忆 ──
  {
    key: 'memory_embedding',
    tab: 'memory',
    label: '语义嵌入',
    labelEn: 'Semantic embedding',
    keywords: 'embedding 语义 嵌入 onnx hash 记忆',
  },
  {
    key: 'memory_consolidation',
    tab: 'memory',
    label: '记忆固化',
    labelEn: 'Memory consolidation',
    keywords: 'consolidation 固化 晋升 衰减 记忆',
  },
  {
    key: 'memory_backup',
    tab: 'memory',
    label: '备份 / 导出 / 导入 / 恢复',
    labelEn: 'Backup & restore',
    keywords: 'backup export import restore 备份 导出 导入 恢复 数据安全',
  },

  // ── 网络 ──
  {
    key: 'remote_workspaces',
    tab: 'remote-workspaces',
    label: '远程工作区（MCP）',
    labelEn: 'Remote workspaces (MCP)',
    keywords: 'remote workspace mcp 远程 工作区 隧道 tunnel cloudflare 急停 emergency 共享 share',
  },
  {
    key: 'network_policy',
    tab: 'network',
    label: '网络模式',
    labelEn: 'Network mode',
    keywords: 'network 网络 模式 内网 气隙 offline intranet online',
  },
  {
    key: 'allowed_hosts',
    tab: 'network',
    label: '主机白名单',
    labelEn: 'Allowed hosts',
    keywords: 'whitelist 白名单 主机 allowed_hosts',
  },
  {
    key: 'insecure_tls',
    tab: 'network',
    label: '跳过 TLS 校验的主机',
    labelEn: 'Insecure TLS hosts',
    keywords: 'tls 证书 自签 insecure',
  },
  {
    key: 'web_proxy',
    tab: 'network',
    label: '抓取代理',
    labelEn: 'Web proxy',
    keywords: 'proxy 代理 http https web_proxy',
  },
  {
    key: 'search_config',
    tab: 'network',
    label: '搜索引擎',
    labelEn: 'Search engines',
    keywords: 'search 搜索 bing ddg tavily zhipu 智谱',
  },
  {
    key: 'web_credentials',
    tab: 'network',
    label: '网站凭据',
    labelEn: 'Site credentials',
    keywords: 'credential 凭据 cookie 登录 header 浏览器',
  },

  // ── MCP ──
  {
    key: 'mcp',
    tab: 'mcp',
    label: 'MCP 服务器',
    labelEn: 'MCP servers',
    keywords: 'mcp server stdio sse oauth 工具 服务器',
  },

  // ── Zotero ──
  {
    key: 'zotero',
    tab: 'zotero',
    label: 'Zotero 文献库',
    labelEn: 'Zotero Library',
    keywords: 'zotero 文献 参考文献 library 文献库 引用 cite',
  },

  // ── 开发环境 ──
  {
    key: 'runtime',
    tab: 'runtime',
    label: '运行时探测与诊断',
    labelEn: 'Runtime probes',
    keywords: 'runtime python node 探测 诊断 试跑 开发环境',
  },

  // ── 进化 ──
  {
    key: 'evolution',
    tab: 'evolution',
    label: '进化面板与日志',
    labelEn: 'Evolution',
    keywords: 'evolution 进化 日志',
  },

  // ── 更新 ──
  {
    key: 'updates',
    tab: 'updates',
    label: '更新策略与通道',
    labelEn: 'Updates',
    keywords: 'update 更新 策略 通道 stable beta 检查更新',
  },
  {
    key: 'providers',
    tab: 'providers',
    label: '更新源管理',
    labelEn: 'Update sources',
    keywords: 'provider 更新源 镜像 源管理',
  },
];

export function searchSettings(query: string): SettingsSearchEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const terms = q.split(/\s+/).filter(Boolean);
  return SETTINGS_SEARCH_INDEX.filter((entry) => {
    const haystack = `${entry.keywords} ${entry.label} ${entry.labelEn} ${entry.key}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });
}
